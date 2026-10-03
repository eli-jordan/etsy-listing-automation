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
