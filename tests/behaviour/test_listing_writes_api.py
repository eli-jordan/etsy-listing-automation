"""The listings API's writes and the files that follow a listing (market-seo
implementation plan, PR 3).

Two things, both through the HTTP surface against a writable fixture
workspace:

- **The market snapshot follows the listing**, as ``.cache/renders/{name}/``
  does: a rename moves it, and a delete removes it on both paths -- the wipe,
  and ``lifecycle: deleted``, which leaves the listing pending its remote
  deletion but has already said the seller is done with it.
- **The per-listing write lock.** Each write is read, merge, write; two of
  them interleaved lose whichever wrote first. The tests widen the window
  between the read and the write by slowing ``yaml.safe_dump`` (the step
  every listing write passes through) or ``Path.rename``, so the
  interleaving is not left to chance.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from etsy_listings.engine.lock import Lockfile
from etsy_listings.ui.api.app import create_app
from etsy_listings.workspace.workspace import Workspace

NAME = "take-a-hike"


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


@pytest.fixture
def client(workspace: Workspace) -> TestClient:
    return TestClient(create_app(workspace))


def _seed_snapshot(workspace: Workspace, name: str = NAME) -> Path:
    path = workspace.market_snapshot_file(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"seeded": true}', encoding="utf-8")
    return path


def _listing(workspace: Workspace, name: str = NAME) -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(
        workspace.listing_file(name).read_text(encoding="utf-8")
    )
    return loaded


@pytest.fixture
def slow_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every listing write serialises its document with ``yaml.safe_dump``
    after reading and merging; a pause there holds the read-to-write window
    open long enough for a second request to land inside it."""
    real = yaml.safe_dump

    def slow(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        time.sleep(0.3)
        return real(*args, **kwargs)

    monkeypatch.setattr(yaml, "safe_dump", slow)


@pytest.fixture
def slow_renames(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rename checks the new name is free, then moves the directory; a
    pause before the move holds that window open the same way."""
    real = Path.rename

    def slow(self: Path, target: Any) -> Path:  # noqa: ANN401
        time.sleep(0.3)
        return real(self, target)

    monkeypatch.setattr(Path, "rename", slow)


def _together(*requests: Callable[[], httpx.Response]) -> list[httpx.Response]:
    """Start each request a moment after the one before, so they overlap in
    a known order."""
    with ThreadPoolExecutor(max_workers=len(requests)) as pool:
        futures = []
        for request in requests:
            futures.append(pool.submit(request))
            time.sleep(0.1)
        return [future.result() for future in futures]


# ------------------------------------------------------------ the snapshot


class TestSnapshotFollowsTheListing:
    def test_a_rename_moves_the_snapshot(self, client: TestClient, workspace: Workspace) -> None:
        _seed_snapshot(workspace)

        response = client.post(f"/api/listings/{NAME}/rename", json={"new_name": "hike-away"})

        assert response.status_code == 200
        assert not workspace.market_snapshot_file(NAME).exists()
        moved = workspace.market_snapshot_file("hike-away")
        assert moved.read_text(encoding="utf-8") == '{"seeded": true}'

    def test_a_rename_without_a_snapshot_still_renames(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        response = client.post(f"/api/listings/{NAME}/rename", json={"new_name": "hike-away"})

        assert response.status_code == 200
        assert not workspace.market_snapshot_file("hike-away").exists()

    def test_deleting_a_listing_with_no_remotes_removes_its_snapshot(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        snapshot = _seed_snapshot(workspace)
        other = _seed_snapshot(workspace, "someone-else")

        assert client.delete(f"/api/listings/{NAME}").status_code == 204

        assert not snapshot.exists()
        assert other.exists()

    def test_marking_a_listing_deleted_removes_its_snapshot(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        Lockfile.empty(tool_version="test", applied_at="2024-01-01T00:00:00").model_copy(
            update={"remote": {"printify_product_id": "abc123"}, "stages_completed": ["render"]}
        ).write(workspace.lock_file(NAME))
        snapshot = _seed_snapshot(workspace)

        response = client.delete(f"/api/listings/{NAME}")

        assert response.status_code == 200
        assert response.json()["status"] == "pending-delete"
        assert not snapshot.exists()


# -------------------------------------------------------- the write lock


@pytest.mark.usefixtures("slow_writes")
class TestWriteLock:
    def test_two_concurrent_patches_both_land(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        brief, title = _together(
            lambda: client.patch(f"/api/listings/{NAME}", json={"brief": "A sunset hike."}),
            lambda: client.patch(
                f"/api/listings/{NAME}", json={"etsy": {"title": "Take A Hike Tee"}}
            ),
        )

        assert (brief.status_code, title.status_code) == (200, 200)
        written = _listing(workspace)
        assert written["brief"] == "A sunset hike."
        assert written["etsy"]["title"] == "Take A Hike Tee"

    def test_a_patch_queued_behind_a_rename_finds_the_listing_gone(
        self, client: TestClient, workspace: Workspace, slow_renames: None
    ) -> None:
        """The rename holds the lock while it moves the directory; the PATCH
        that was waiting must not then write a fresh ``listing.yaml`` under
        the old name."""
        rename, edit = _together(
            lambda: client.post(f"/api/listings/{NAME}/rename", json={"new_name": "hike-away"}),
            lambda: client.patch(f"/api/listings/{NAME}", json={"brief": "Too late."}),
        )

        assert rename.status_code == 200
        assert edit.status_code == 404
        assert not workspace.listing_dir(NAME).exists()
        assert _listing(workspace, "hike-away").get("brief") != "Too late."

    def test_a_create_and_a_rename_to_the_same_name_do_not_both_win(
        self, client: TestClient, workspace: Workspace, slow_renames: None
    ) -> None:
        document = _listing(workspace)

        rename, create = _together(
            lambda: client.post(f"/api/listings/{NAME}/rename", json={"new_name": "fresh"}),
            lambda: client.post("/api/listings", json={"name": "fresh", "document": document}),
        )

        assert sorted([rename.status_code, create.status_code]) == [200, 409]
        assert workspace.listing_file("fresh").is_file()
