"""The staging and batch endpoints' HTTP surface (batch plan PR 2; A37-A39,
A45, A46): status codes, payload shape, and what is on disk after each answer.

The staging and creation rules are `batches`' and have their own behaviour
tests; these pin what the browser is told, and that a reload finds the same
session again.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from etsy_listings.batches import StagingStore, stage_pngs
from etsy_listings.ui.api.app import create_app
from etsy_listings.workspace.workspace import Workspace

from tests.support.batches import LISTING_TEMPLATE, a_listing_template, png, uploads


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    workspace = Workspace.discover(root_override=workspace_root)
    a_listing_template(workspace)
    return workspace


@pytest.fixture
def client(workspace: Workspace) -> TestClient:
    return TestClient(create_app(workspace))


def _stage(client: TestClient, *files: tuple[str, bytes], template: str = LISTING_TEMPLATE) -> Any:  # noqa: ANN401
    return client.post(
        "/api/staging",
        data={"listing_template": template},
        files=[("files", (name, data, "image/png")) for name, data in files],
    )


def _staged(client: TestClient, *files: tuple[str, bytes]) -> dict[str, Any]:
    response = _stage(client, *files)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


class TestStage:
    def test_staging_answers_the_session_and_a_reload_reattaches_to_it(
        self, client: TestClient
    ) -> None:
        staged = _staged(
            client, ("Night Hike Club.png", png(1)), ("sketch.png", png(2, mode="RGB"))
        )

        assert staged["listing_template"] == LISTING_TEMPLATE
        assert staged["label"].startswith(f"{LISTING_TEMPLATE} · ")
        assert [(r["sources"], r["name"], r["state"]) for r in staged["rows"]] == [
            (["Night Hike Club.png"], "night-hike-club", "ready"),
            (["sketch.png"], "sketch", "invalid"),
        ]

        reloaded = client.get(f"/api/staging/{staged['id']}")

        assert reloaded.status_code == 200
        assert reloaded.json() == staged

    def test_a_refused_upload_is_a_422_with_the_remedy_and_nothing_on_disk(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        response = _stage(client, *[(f"d{n}.png", png(n)) for n in range(26)])

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "26 different PNG designs" in detail["message"]
        assert detail["remedy"].endswith("Nothing was uploaded or changed.")
        assert workspace.staging_ids() == []

    def test_a_zip_is_refused_as_coming_soon(self, client: TestClient) -> None:
        response = _stage(client, ("kittl-export.zip", b"PK\x03\x04..."))

        assert response.status_code == 422
        assert "coming soon" in response.json()["detail"]["message"]

    def test_an_unknown_listing_template_is_a_404(self, client: TestClient) -> None:
        assert _stage(client, ("a.png", png(1)), template="nope").status_code == 404

    def test_a_row_s_thumbnail_is_served(self, client: TestClient) -> None:
        staged = _staged(client, ("a.png", png(1)))
        row = staged["rows"][0]["id"]

        response = client.get(f"/api/staging/{staged['id']}/rows/{row}/thumbnail")

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert client.get(f"/api/staging/{staged['id']}/rows/nope/thumbnail").status_code == 404


class TestEdit:
    def test_rename_remove_and_relabel_in_one_patch(self, client: TestClient) -> None:
        staged = _staged(client, ("a.png", png(1)), ("b.png", png(2)))
        first, second = (row["id"] for row in staged["rows"])

        response = client.patch(
            f"/api/staging/{staged['id']}",
            json={"label": "Autumn drop", "names": {first: "take-a-hike"}, "remove": [second]},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["label"] == "Autumn drop"
        assert [(r["name"], r["state"], r["suggestion"]) for r in body["rows"]] == [
            ("take-a-hike", "name", "take-a-hike-2")
        ]
        assert client.get(f"/api/staging/{staged['id']}").json() == body

    def test_an_unknown_row_or_session_is_a_404(self, client: TestClient) -> None:
        staged = _staged(client, ("a.png", png(1)))

        assert (
            client.patch(f"/api/staging/{staged['id']}", json={"remove": ["nope"]}).status_code
            == 404
        )
        assert client.get("/api/staging/0123abcd").status_code == 404

    def test_cancel_removes_the_session(self, client: TestClient, workspace: Workspace) -> None:
        staged = _staged(client, ("a.png", png(1)))

        assert client.delete(f"/api/staging/{staged['id']}").status_code == 204
        assert workspace.staging_ids() == []
        assert client.get(f"/api/staging/{staged['id']}").status_code == 404


class TestConfirm:
    def test_confirm_answers_the_batch_and_the_batch_reads_back(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        staged = _staged(client, ("Night Hike Club.png", png(1)), ("lake_loop.png", png(2)))

        response = client.post(f"/api/staging/{staged['id']}/confirm")

        assert response.status_code == 200
        batch = response.json()
        assert batch["id"] == staged["id"]
        assert batch["label"] == staged["label"]
        assert [(r["name"], r["creation"]) for r in batch["rows"]] == [
            ("night-hike-club", "created"),
            ("lake-loop", "created"),
        ]
        assert client.get(f"/api/batches/{batch['id']}").json() == batch
        assert workspace.listing_file("lake-loop").is_file()
        cards = client.get("/api/listing-templates").json()
        assert cards[0]["batch_count"] == 1

    def test_a_name_to_fix_is_a_409_with_nothing_created(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        staged = _staged(client, ("★★★.png", png(1)))

        response = client.post(f"/api/staging/{staged['id']}/confirm")

        assert response.status_code == 409
        assert response.json()["detail"] == "Fix 1 names to create the listings."
        assert workspace.listing_names() == ["take-a-hike"]

    def test_retry_creates_a_failed_row(self, client: TestClient, workspace: Workspace) -> None:
        staged = _staged(client, ("a.png", png(1)))
        blocker = workspace.design_file("a")
        blocker.mkdir(parents=True)
        batch = client.post(f"/api/staging/{staged['id']}/confirm").json()
        row = batch["rows"][0]
        assert row["creation"] == "failed"
        blocker.rmdir()

        response = client.post(f"/api/batches/{batch['id']}/rows/{row['id']}/retry")

        assert response.status_code == 200
        assert response.json()["rows"][0]["creation"] == "created"
        assert client.post(f"/api/batches/{batch['id']}/rows/nope/retry").status_code == 404

    def test_an_unknown_batch_is_a_404(self, client: TestClient) -> None:
        assert client.get("/api/batches/0123abcd").status_code == 404
        assert client.post("/api/staging/0123abcd/confirm").status_code == 404


def test_the_listing_template_card_carries_the_design_size_it_needs(client: TestClient) -> None:
    card = client.get("/api/listing-templates").json()[0]

    assert card["design_minimum"] == {"width": 90, "height": 108}


def test_an_expired_session_is_swept_when_the_server_starts(workspace: Workspace) -> None:
    week_ago = datetime.now(UTC) - timedelta(days=7, minutes=1)
    stale = stage_pngs(
        workspace,
        StagingStore(workspace),
        LISTING_TEMPLATE,
        uploads(("a.png", png(1))),
        now=week_ago,
    )
    fresh = stage_pngs(
        workspace, StagingStore(workspace), LISTING_TEMPLATE, uploads(("b.png", png(2)))
    )

    with TestClient(create_app(workspace)) as client:
        assert client.get(f"/api/staging/{stale.id}").status_code == 404
        assert client.get(f"/api/staging/{fresh.id}").status_code == 200
