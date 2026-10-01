"""The status codes the listings API answers when its writes compete.

The coordination itself -- the per-listing write lock, the existence re-check
once it is held, the files that follow a rename or go with a delete -- is the
listing operations' and is tested directly in ``test_listing_operations.py``.
What is left here is the adapter's half: that the routes hand every request
the process's one set of locks, and that a refusal reached under the lock
becomes the same status code as one reached before it. The overlap is
forced by slowing ``Path.rename`` so it is not left to chance.
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

from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app

NAME = "take-a-hike"


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


@pytest.fixture
def client(workspace: Workspace) -> TestClient:
    return TestClient(create_app(workspace))


def _listing(workspace: Workspace, name: str = NAME) -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(
        workspace.listing_file(name).read_text(encoding="utf-8")
    )
    return loaded


@pytest.fixture
def slow_renames(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rename checks the new name is free, then moves the directory; a
    pause before the move holds that window open."""
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


@pytest.mark.usefixtures("slow_renames")
class TestCompetingWrites:
    def test_a_patch_queued_behind_a_rename_is_a_404(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        rename, edit = _together(
            lambda: client.post(f"/api/listings/{NAME}/rename", json={"new_name": "hike-away"}),
            lambda: client.patch(f"/api/listings/{NAME}", json={"brief": "Too late."}),
        )

        assert rename.status_code == 200
        assert edit.status_code == 404
        assert not workspace.listing_dir(NAME).exists()

    def test_a_create_and_a_rename_to_the_same_name_are_a_200_and_a_409(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        document = _listing(workspace)

        rename, create = _together(
            lambda: client.post(f"/api/listings/{NAME}/rename", json={"new_name": "fresh"}),
            lambda: client.post("/api/listings", json={"name": "fresh", "document": document}),
        )

        assert sorted([rename.status_code, create.status_code]) == [200, 409]
        assert workspace.listing_file("fresh").is_file()
