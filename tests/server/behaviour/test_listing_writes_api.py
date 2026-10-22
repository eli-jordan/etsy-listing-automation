"""The status codes the listings API answers when its writes compete.

The coordination itself -- the per-listing write lock, the existence re-check
once it is held, the files that follow a rename or go with a delete -- is the
listing operations' and is tested directly in ``test_listing_operations.py``.
What is left here is the adapter's half: that the routes hand every request
the process's one set of locks, and that a refusal reached under the lock
becomes the same status code as one reached before it. The overlap is
forced at the persistence seam: the first request's handler holds the
listing's lock at a bounded gate, and the second is sent only once it does.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from etsy_listings.core.workspace.listing_documents import ListingDocuments
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app

from tests.support.gates import LockGate, workers

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
def listing_lock(monkeypatch: pytest.MonkeyPatch) -> LockGate:
    """The first request to take a listing's lock holds it until released."""
    gate = LockGate("the listing")
    real = ListingDocuments.lock

    def gated(self: ListingDocuments, name: str, *more: str) -> AbstractContextManager[None]:
        return gate.around(lambda: real(self, name, *more))

    monkeypatch.setattr(ListingDocuments, "lock", gated)
    return gate


def _contend(
    gate: LockGate,
    holder: Callable[[], httpx.Response],
    contender: Callable[[], httpx.Response],
) -> tuple[httpx.Response, httpx.Response]:
    """Send ``holder`` until its handler holds the lock, then ``contender``;
    check the contender waits outside, release, and return both responses."""
    with workers(gate) as start:
        first = start("holder", holder)
        gate.held.wait_entered()
        second = start("contender", contender)
        gate.assert_contender_kept_out()
        gate.held.release()
        return cast(httpx.Response, first.result()), cast(httpx.Response, second.result())


class TestCompetingWrites:
    def test_a_patch_queued_behind_a_rename_is_a_404(
        self, client: TestClient, workspace: Workspace, listing_lock: LockGate
    ) -> None:
        rename, edit = _contend(
            listing_lock,
            lambda: client.post(f"/api/listings/{NAME}/rename", json={"new_name": "hike-away"}),
            lambda: client.patch(f"/api/listings/{NAME}", json={"brief": "Too late."}),
        )

        assert rename.status_code == 200
        assert edit.status_code == 404
        assert not workspace.listing_dir(NAME).exists()
        assert _listing(workspace, "hike-away").get("brief") != "Too late."

    def test_a_create_and_a_rename_to_the_same_name_are_a_200_and_a_409(
        self, client: TestClient, workspace: Workspace, listing_lock: LockGate
    ) -> None:
        document = _listing(workspace)

        rename, create = _contend(
            listing_lock,
            lambda: client.post(f"/api/listings/{NAME}/rename", json={"new_name": "fresh"}),
            lambda: client.post("/api/listings", json={"name": "fresh", "document": document}),
        )

        assert (rename.status_code, create.status_code) == (200, 409)
        assert not workspace.listing_dir(NAME).exists()
        assert workspace.listing_file("fresh").is_file()


class TestDesignWrittenAsAMap:
    """Every write normalises ``design:`` to its map form (multi-artwork plan,
    *Settled decisions*): a bare string or ``null`` still loads, and the next
    write converges it on the one written form."""

    def test_a_patch_writes_the_fixtures_bare_string_back_as_a_map(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        assert _listing(workspace)["design"] == "designs/take-a-hike.png"

        client.patch(f"/api/listings/{NAME}", json={"brief": "Changed."})

        assert _listing(workspace)["design"] == {"default": "designs/take-a-hike.png"}

    def test_a_patch_of_null_writes_an_empty_map(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        body = client.patch(f"/api/listings/{NAME}", json={"design": None}).json()

        assert body["field_errors"] == {}
        assert _listing(workspace)["design"] == {}

    def test_a_malformed_map_is_a_field_error_and_writes_nothing(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        before = _listing(workspace)
        body = client.patch(
            f"/api/listings/{NAME}",
            json={"design": {"default": "designs/a.png", "on-dark": "designs/b.png"}},
        ).json()

        assert "default cannot be combined" in body["field_errors"]["design"]
        assert _listing(workspace) == before

    def test_an_empty_light_dark_pair_survives_a_reload(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        """Acceptance 3: the mode with no files chosen yet is recorded by its
        two ``null`` keys, and a GET hands them back as they were written."""
        pair = {"on-light": None, "on-dark": None}

        body = client.patch(f"/api/listings/{NAME}", json={"design": pair}).json()

        assert body["field_errors"] == {}
        assert _listing(workspace)["design"] == pair
        assert client.get(f"/api/listings/{NAME}").json()["design"] == pair

    def test_a_partial_pair_survives_a_reload(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        pair = {"on-light": None, "on-dark": "designs/take-a-hike.png"}

        client.patch(f"/api/listings/{NAME}", json={"design": pair})

        assert client.get(f"/api/listings/{NAME}").json()["design"] == pair

    def test_a_malformed_map_answers_200_with_the_field_error(self, client: TestClient) -> None:
        response = client.patch(
            f"/api/listings/{NAME}", json={"design": {"moss": "designs/take-a-hike.png"}}
        )

        assert response.status_code == 200
        assert "no base design" in response.json()["field_errors"]["design"]

    def test_a_create_writes_the_map_form(self, client: TestClient, workspace: Workspace) -> None:
        document = {**_listing(workspace), "design": "designs/take-a-hike.png"}

        response = client.post("/api/listings", json={"name": "fresh", "document": document})

        assert response.status_code == 200, response.text
        assert _listing(workspace, "fresh")["design"] == {"default": "designs/take-a-hike.png"}
