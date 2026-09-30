"""The staging and batch endpoints' HTTP surface (batch plan PR 2 and PR 4;
A37-A40, A45, A46): status codes, payload shape, and what is on disk after
each answer.

The staging, creation and queue rules are `batches`' and `ui.batchqueue`'s
and have their own behaviour tests; these pin what the browser is told, and
that a reload finds the same session again. The app is given a
:class:`~tests.support.ai_runs.ChainProvider` and the in-memory Etsy market,
so staging's AI readiness passes unless a test takes one away.
"""

from __future__ import annotations

import zipfile
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from etsy_listings.ai.models import ProviderReadiness
from etsy_listings.batches import StagingStore, stage_pngs
from etsy_listings.ui.api.app import create_app
from etsy_listings.workspace.workspace import Workspace

from tests.support.ai_runs import ChainProvider, seed_prompts, seeded_market, wait_for
from tests.support.batches import LISTING_TEMPLATE, a_listing_template, png, uploads


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    seed_prompts(workspace_root)
    workspace = Workspace.discover(root_override=workspace_root)
    a_listing_template(workspace)
    return workspace


@pytest.fixture
def provider() -> ChainProvider:
    return ChainProvider()


def _app(workspace: Workspace, provider: ChainProvider, *, market: bool = True) -> FastAPI:
    etsy = seeded_market() if market else None
    return create_app(
        workspace,
        seo_provider_factory=lambda _workspace: [provider],
        market_client_factory=lambda _workspace: etsy,
    )


@pytest.fixture
def client(workspace: Workspace, provider: ChainProvider) -> TestClient:
    """No lifespan, so no queue: a confirmed row stays queued."""
    return TestClient(_app(workspace, provider))


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

    def test_a_zip_answers_its_ignored_files_and_each_row_s_reused_design(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        workspace.design_file("fjord-mornings").write_bytes(png(4))
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("exports/fjord-mornings-final.png", png(4))
            archive.writestr("exports/cedar-trail.png", png(2))
            archive.writestr("readme.txt", b"Exported with Kittl")
        response = client.post(
            "/api/staging",
            data={"listing_template": LISTING_TEMPLATE},
            files=[("files", ("kittl-export.zip", buffer.getvalue(), "application/zip"))],
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ignored"] == ["readme.txt"]
        assert [(row["name"], row["reuse"]) for row in body["rows"]] == [
            ("fjord-mornings-final", "fjord-mornings"),
            ("cedar-trail", None),
        ]

    def test_two_zips_are_a_422_with_nothing_on_disk(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        response = client.post(
            "/api/staging",
            data={"listing_template": LISTING_TEMPLATE},
            files=[
                ("files", ("a.zip", b"PK\x03\x04", "application/zip")),
                ("files", ("b.zip", b"PK\x03\x04", "application/zip")),
            ],
        )

        assert response.status_code == 422
        assert response.json()["detail"]["message"] == "These are 2 ZIPs, and a batch takes one."
        assert workspace.staging_ids() == []

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
        assert response.json()["detail"] == "Fix 1 name to create the listings."
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


class TestAiReadiness:
    """Spec, *Design validation*: a batch is not knowingly created into a
    queue that cannot run. Nothing is said while it can."""

    def test_nothing_is_said_while_ai_can_run(self, client: TestClient) -> None:
        assert _staged(client, ("a.png", png(1)))["ai_blocked"] is None

    def test_a_missing_prompt_is_named_and_confirm_writes_nothing(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        staged = _staged(client, ("a.png", png(1)))
        workspace.brief_prompt_file().unlink()

        reloaded = client.get(f"/api/staging/{staged['id']}").json()
        response = client.post(f"/api/staging/{staged['id']}/confirm")

        assert reloaded["ai_blocked"] == {
            "message": "prompts/brief.md is missing.",
            "remedy": "Run `etsy-listings setup` to seed it, then come back. Your staging is kept.",
        }
        assert response.status_code == 409
        assert response.json()["detail"] == (
            "AI drafting can't run yet. prompts/brief.md is missing."
        )
        assert workspace.listing_names() == ["take-a-hike"]
        assert workspace.batch_ids() == []
        assert client.get(f"/api/staging/{staged['id']}").status_code == 200

    def test_no_ready_provider_blocks(self, client: TestClient, provider: ChainProvider) -> None:
        provider.ready = ProviderReadiness(ready=False, reason="codex: not signed in")

        blocked = _staged(client, ("a.png", png(1)))["ai_blocked"]

        assert blocked["message"] == "No AI provider is ready."
        assert blocked["remedy"] == "Add one in Setup, then come back. Your staging is kept."

    def test_no_etsy_market_access_blocks(
        self, workspace: Workspace, provider: ChainProvider
    ) -> None:
        client = TestClient(_app(workspace, provider, market=False))

        blocked = _staged(client, ("a.png", png(1)))["ai_blocked"]

        assert blocked["message"] == "Etsy market access isn't set up."


def _ai(client: TestClient, batch_id: str) -> list[tuple[str, str | None]]:
    return [(r["name"], r["ai"]) for r in client.get(f"/api/batches/{batch_id}").json()["rows"]]


class TestQueue:
    def test_confirm_queues_every_created_row_in_order(self, client: TestClient) -> None:
        staged = _staged(client, ("a.png", png(1)), ("b.png", png(2)))

        batch = client.post(f"/api/staging/{staged['id']}/confirm").json()

        assert [(r["ai"], r["queue_position"]) for r in batch["rows"]] == [
            ("queued", 1),
            ("queued", 2),
        ]
        assert batch["concurrency"] == 1

    def test_a_manual_run_is_refused_while_the_row_is_queued_and_allowed_once_done(
        self, workspace: Workspace, provider: ChainProvider
    ) -> None:
        gate = provider.gate("brief")
        with TestClient(_app(workspace, provider)) as client:
            staged = _staged(client, ("a.png", png(1)), ("b.png", png(2)))
            batch = client.post(f"/api/staging/{staged['id']}/confirm").json()
            wait_for(lambda: _ai(client, batch["id"]) == [("a", "running"), ("b", "queued")])

            refused = client.post("/api/ai/runs", json={"listing": "b", "draft_brief": True})
            readiness = client.get("/api/listings/b/ai-seo/readiness").json()
            gate.set()
            wait_for(lambda: _ai(client, batch["id"]) == [("a", "done"), ("b", "done")])
            allowed = client.post("/api/ai/runs", json={"listing": "b", "draft_brief": False})

        assert refused.status_code == 409
        assert refused.json() == {"active_run": None, "reason": "batch_pending"}
        assert readiness["ready"] is False
        assert readiness["batch_pending"] is True
        assert allowed.status_code == 202, allowed.text
        assert allowed.json()["origin"] == "manual"

    def test_a_row_shows_its_live_steps_then_its_proposal(
        self, workspace: Workspace, provider: ChainProvider
    ) -> None:
        gate = provider.gate("queries")
        with TestClient(_app(workspace, provider)) as client:
            staged = _staged(client, ("a.png", png(1)))
            batch_id = client.post(f"/api/staging/{staged['id']}/confirm").json()["id"]
            wait_for(lambda: provider.started["queries"].is_set())

            live = client.get(f"/api/batches/{batch_id}").json()["rows"][0]
            gate.set()
            wait_for(lambda: _ai(client, batch_id) == [("a", "done")])
            done = client.get(f"/api/batches/{batch_id}").json()["rows"][0]
            proposal = client.get("/api/listings/a/proposal").json()

        assert [(s["id"], s["state"]) for s in live["ai_steps"]] == [
            ("brief", "done"),
            ("market", "active"),
            ("seo", "pending"),
        ]
        assert live["proposal"] is None
        assert done["proposal"] == "ready"
        assert proposal["origin"] == "batch"

    def test_cancel_resume_and_retry_answer_the_batch(self, client: TestClient) -> None:
        staged = _staged(client, ("a.png", png(1)), ("b.png", png(2)))
        batch_id = client.post(f"/api/staging/{staged['id']}/confirm").json()["id"]

        cancelled = client.post(f"/api/batches/{batch_id}/cancel")
        row = cancelled.json()["rows"][0]["id"]
        retried = client.post(f"/api/batches/{batch_id}/rows/{row}/retry")
        resumed = client.post(f"/api/batches/{batch_id}/resume")
        nothing = client.post(f"/api/batches/{batch_id}/rows/{row}/retry")

        assert [r["ai"] for r in cancelled.json()["rows"]] == ["stopped", "stopped"]
        assert [r["ai"] for r in retried.json()["rows"]] == ["queued", "stopped"]
        assert [r["ai"] for r in resumed.json()["rows"]] == ["queued", "queued"]
        assert nothing.status_code == 409
        assert client.post("/api/batches/0123abcd/cancel").status_code == 404

    def test_retry_all_failed_creates_the_failed_row_and_queues_it(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        staged = _staged(client, ("a.png", png(1)))
        blocker = workspace.design_file("a")
        blocker.mkdir(parents=True)
        batch = client.post(f"/api/staging/{staged['id']}/confirm").json()
        assert batch["rows"][0]["ai"] is None
        blocker.rmdir()

        retried = client.post(f"/api/batches/{batch['id']}/retry").json()

        assert [(r["creation"], r["ai"]) for r in retried["rows"]] == [("created", "queued")]


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


def _confirmed(client: TestClient, *files: tuple[str, bytes]) -> dict[str, Any]:
    staged = _staged(client, *files)
    body: dict[str, Any] = client.post(f"/api/staging/{staged['id']}/confirm").json()
    return body


class TestIndex:
    """Recent batches (UI doc §2; batch plan PR 5)."""

    def test_a_batch_and_an_unconfirmed_session_are_listed_newest_first(
        self, client: TestClient
    ) -> None:
        confirmed = _confirmed(client, ("a.png", png(1)), ("b.png", png(2)))
        waiting = _staged(client, ("c.png", png(3)))

        index = client.get("/api/batches")

        assert index.status_code == 200
        staging, batch = index.json()
        assert (staging["kind"], staging["id"], staging["status"]) == (
            "staging",
            waiting["id"],
            "staging",
        )
        assert (staging["designs"], staging["expires_at"]) == (1, waiting["expires_at"])
        assert (batch["kind"], batch["id"], batch["status"]) == (
            "batch",
            confirmed["id"],
            "drafting",
        )
        assert (batch["designs"], batch["listings"], batch["failures"]) == (2, 2, 0)
        assert batch["expires_at"] is None

    def test_a_session_kept_for_a_failed_row_is_the_batch_s_not_a_staging_row(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        """A46 keeps a confirmed session until every row is materialised; it
        shares the batch's id, and Recent batches shows the batch once."""
        staged = _staged(client, ("a.png", png(1)), ("b.png", png(2)))
        store = StagingStore(workspace)
        session = store.load(staged["id"])
        assert session is not None
        workspace.design_file("a").mkdir(parents=True)
        client.post(f"/api/staging/{staged['id']}/confirm")
        store.save(session)  # as if the failed row's upload could not be moved

        index = client.get("/api/batches").json()

        assert [(entry["kind"], entry["failures"]) for entry in index] == [("batch", 1)]

    def test_an_expired_session_is_swept_when_the_index_is_listed(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        week_ago = datetime.now(UTC) - timedelta(days=7, minutes=1)
        store = StagingStore(workspace)
        stage_pngs(workspace, store, LISTING_TEMPLATE, uploads(("a.png", png(1))), now=week_ago)

        assert client.get("/api/batches").json() == []
        assert workspace.staging_ids() == []


class TestRenameAndDelete:
    def test_rename_changes_the_label_and_keeps_the_id(self, client: TestClient) -> None:
        batch_id = _confirmed(client, ("a.png", png(1)))["id"]

        renamed = client.patch(f"/api/batches/{batch_id}", json={"label": "Autumn drop"})
        blank = client.patch(f"/api/batches/{batch_id}", json={"label": "  "})

        assert renamed.status_code == 200
        assert (renamed.json()["id"], renamed.json()["label"]) == (batch_id, "Autumn drop")
        assert blank.json()["label"] == "Autumn drop"
        assert client.get("/api/batches").json()[0]["label"] == "Autumn drop"
        assert client.patch("/api/batches/0123abcd", json={"label": "x"}).status_code == 404

    def test_delete_is_a_204_and_then_a_404(self, client: TestClient) -> None:
        batch_id = _confirmed(client, ("a.png", png(1)))["id"]

        assert client.delete(f"/api/batches/{batch_id}").status_code == 204
        assert client.delete(f"/api/batches/{batch_id}").status_code == 404


class TestReviewed:
    def test_a_queued_row_is_refused_with_a_409(self, client: TestClient) -> None:
        """No lifespan, so no queue: the row stays queued."""
        batch = _confirmed(client, ("a.png", png(1)))
        row = batch["rows"][0]
        assert (row["reviewed"], row["reviewable"]) == (False, False)

        response = client.put(
            f"/api/batches/{batch['id']}/rows/{row['id']}/reviewed", json={"reviewed": True}
        )

        assert response.status_code == 409
        assert response.json()["detail"] == "a has no listing to review yet"

    def test_a_never_created_row_is_refused_and_an_unknown_one_is_a_404(
        self, client: TestClient, workspace: Workspace
    ) -> None:
        staged = _staged(client, ("a.png", png(1)))
        workspace.design_file("a").mkdir(parents=True)
        batch = client.post(f"/api/staging/{staged['id']}/confirm").json()
        url = f"/api/batches/{batch['id']}/rows"

        failed = client.put(f"{url}/{batch['rows'][0]['id']}/reviewed", json={"reviewed": True})
        unknown = client.put(f"{url}/nope/reviewed", json={"reviewed": True})

        assert (failed.status_code, unknown.status_code) == (409, 404)

    def test_a_stopped_row_is_marked_and_the_answer_is_the_batch(self, client: TestClient) -> None:
        batch = _confirmed(client, ("a.png", png(1)))
        client.post(f"/api/batches/{batch['id']}/cancel")
        row = batch["rows"][0]["id"]

        response = client.put(
            f"/api/batches/{batch['id']}/rows/{row}/reviewed", json={"reviewed": True}
        )

        assert response.status_code == 200
        assert response.json()["rows"][0]["reviewed"] is True
        assert response.json()["status"] == "complete"


class TestListingMembership:
    def test_a_batch_listing_names_its_batch_and_row(self, client: TestClient) -> None:
        batch = _confirmed(client, ("a.png", png(1)))

        membership = client.get("/api/listings/a/batch")

        assert membership.status_code == 200
        assert membership.json() == {
            "batch_id": batch["id"],
            "label": batch["label"],
            "row_id": batch["rows"][0]["id"],
            "reviewed": False,
            "reviewable": False,
        }

    def test_a_listing_no_batch_made_is_null(self, client: TestClient) -> None:
        assert client.get("/api/listings/take-a-hike/batch").json() is None


def test_a_row_that_was_never_created_shows_its_kept_upload(
    client: TestClient, workspace: Workspace
) -> None:
    """Its upload went beside the batch (A46), since the staging session has
    gone; that is its thumbnail on the summary."""
    staged = _staged(client, ("a.png", png(1)))
    workspace.design_file("a").mkdir(parents=True)
    batch = client.post(f"/api/staging/{staged['id']}/confirm").json()
    assert workspace.staging_ids() == []
    rows = f"/api/batches/{batch['id']}/rows"

    response = client.get(f"{rows}/{batch['rows'][0]['id']}/thumbnail")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert client.get(f"{rows}/nope/thumbnail").status_code == 404
