"""Reviewing a batch, and a batch's listings living on after it (batch plan
PR 5; spec *Review workflow*, *Cancellation and deletion* and *Error and
recovery rules*; UI doc §2 and §7; rename and delete hooks).

Everything goes through the app the seller drives -- the staging, batch,
listing and AI-run endpoints, with the batch queue running -- because what
these pin is how those surfaces meet: a listing renamed in the editor is
the one the summary opens, a listing deleted leaves its row, and deleting a
batch's record leaves every file it made. The provider is a
:class:`~tests.support.ai_runs.ChainProvider` over the in-memory market.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from etsy_listings.core.ai.proposals import ProposalStore
from etsy_listings.core.clients.printify.fakes import FakePrintifyClient
from etsy_listings.core.engine.lock import Lockfile
from etsy_listings.core.engine.run import plan_listings
from etsy_listings.core.engine.stages import STAGES
from etsy_listings.core.workspace.workspace import Workspace, remove_tree
from etsy_listings.ui.api.app import create_app

from tests.support.ai_runs import ChainProvider, seed_prompts, seeded_market, wait_for
from tests.support.batches import LISTING_TEMPLATE, a_listing_template, png
from tests.support.builders import a_context


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    seed_prompts(workspace_root)
    workspace = Workspace.discover(root_override=workspace_root)
    a_listing_template(workspace)
    return workspace


@pytest.fixture
def provider() -> ChainProvider:
    return ChainProvider()


@pytest.fixture
def client(workspace: Workspace, provider: ChainProvider) -> Iterator[TestClient]:
    """With the lifespan, so the batch queue drafts every row."""
    market = seeded_market()
    app = create_app(
        workspace,
        seo_provider_factory=lambda _workspace: [provider],
        market_client_factory=lambda _workspace: market,
    )
    with TestClient(app) as client:
        yield client


def _batch(client: TestClient, *names: str) -> str:
    staged = client.post(
        "/api/staging",
        data={"listing_template": LISTING_TEMPLATE},
        files=[("files", (f"{n}.png", png(i + 1), "image/png")) for i, n in enumerate(names)],
    )
    assert staged.status_code == 200, staged.text
    confirmed = client.post(f"/api/staging/{staged.json()['id']}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    batch_id: str = confirmed.json()["id"]
    return batch_id


def _summary(client: TestClient, batch_id: str) -> dict[str, Any]:
    response = client.get(f"/api/batches/{batch_id}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _drafted(client: TestClient, batch_id: str) -> dict[str, Any]:
    wait_for(lambda: all(r["ai"] == "done" for r in _summary(client, batch_id)["rows"]))
    return _summary(client, batch_id)


def _status(client: TestClient, batch_id: str) -> str:
    entry = next(b for b in client.get("/api/batches").json() if b["id"] == batch_id)
    status: str = entry["status"]
    return status


def _review(client: TestClient, batch_id: str, row: str, *, reviewed: bool = True) -> Any:  # noqa: ANN401
    return client.put(f"/api/batches/{batch_id}/rows/{row}/reviewed", json={"reviewed": reviewed})


# ---------------------------------------------------------------- review


def test_the_last_listing_reviewed_completes_the_batch_and_one_back_reopens_it(
    client: TestClient,
) -> None:
    batch_id = _batch(client, "night-hike-club", "cedar-trail")
    first, second = (row["id"] for row in _drafted(client, batch_id)["rows"])
    assert _status(client, batch_id) == "in_review"

    assert _review(client, batch_id, first).status_code == 200
    assert _status(client, batch_id) == "in_review"
    assert _review(client, batch_id, second).status_code == 200
    assert _status(client, batch_id) == "complete"

    _review(client, batch_id, first, reviewed=False)

    assert _status(client, batch_id) == "in_review"
    assert [r["reviewed"] for r in _summary(client, batch_id)["rows"]] == [False, True]


def test_a_later_edit_or_a_regenerated_proposal_leaves_reviewed_alone(
    client: TestClient, workspace: Workspace
) -> None:
    """Spec, *Review workflow*: Reviewed is the seller's judgement, and
    nothing else resets it."""
    batch_id = _batch(client, "night-hike-club")
    row = _drafted(client, batch_id)["rows"][0]["id"]
    _review(client, batch_id, row)
    before = ProposalStore(workspace).load("night-hike-club")

    patched = client.patch("/api/listings/night-hike-club", json={"brief": "Rewritten brief."})
    assert patched.status_code == 200, patched.text
    run = client.post("/api/ai/runs", json={"listing": "night-hike-club"})
    assert run.status_code == 202, run.text
    wait_for(lambda: client.get(f"/api/ai/runs/{run.json()['id']}").json()["phase"] == "done")

    after = ProposalStore(workspace).load("night-hike-club")
    assert before is not None and after is not None
    assert after.generated_at != before.generated_at or after.snapshot != before.snapshot
    assert _summary(client, batch_id)["rows"][0]["reviewed"] is True
    assert _status(client, batch_id) == "complete"


def test_plan_reads_the_same_whether_a_listing_is_reviewed_or_not(
    client: TestClient, workspace_root: Path
) -> None:
    """Review is advisory (spec, *Review workflow*): ``plan`` -- and
    ``apply``, which runs the plan it makes -- never reads it."""
    batch_id = _batch(client, "night-hike-club")
    row = _drafted(client, batch_id)["rows"][0]["id"]

    def plan() -> object:
        context = a_context(workspace_root, printify=FakePrintifyClient([]))  # type: ignore[arg-type]
        return plan_listings(context, ["night-hike-club"], STAGES).outcomes

    unreviewed = plan()
    _review(client, batch_id, row)

    assert plan() == unreviewed


# --------------------------------------------------------------- rename


def test_a_renamed_listing_is_the_one_its_row_opens_and_its_proposal_follows(
    client: TestClient, workspace: Workspace
) -> None:
    batch_id = _batch(client, "night-hike-club", "cedar-trail")
    _drafted(client, batch_id)

    renamed = client.post(
        "/api/listings/night-hike-club/rename", json={"new_name": "night-hike-crew"}
    )
    assert renamed.status_code == 200, renamed.text

    row = _summary(client, batch_id)["rows"][0]
    assert (row["name"], row["proposal"]) == ("night-hike-crew", "ready")
    assert client.get(f"/api/listings/{row['name']}").status_code == 200
    assert ProposalStore(workspace).load("night-hike-club") is None
    membership = client.get("/api/listings/night-hike-crew/batch").json()
    assert (membership["batch_id"], membership["row_id"]) == (batch_id, row["id"])


# --------------------------------------------------------------- delete


def test_deleting_a_listing_cancels_its_run_and_leaves_a_deleted_row(
    client: TestClient, provider: ChainProvider
) -> None:
    gate = provider.gate("brief")
    batch_id = _batch(client, "night-hike-club", "cedar-trail")
    wait_for(lambda: provider.started["brief"].is_set())

    # The queued row first: deleted while the other still holds the one
    # slot, so the queue never starts it. The running one is stopped.
    assert client.delete("/api/listings/cedar-trail").status_code == 204
    assert client.delete("/api/listings/night-hike-club").status_code == 204

    wait_for(lambda: provider.cancelled == ["brief"])
    wait_for(lambda: _summary(client, batch_id)["rows"][0]["ai"] == "cancelled")
    rows = _summary(client, batch_id)["rows"]
    assert [(r["deleted"], r["ai"], r["reviewable"]) for r in rows] == [
        (True, "cancelled", False),
        (True, "cancelled", False),
    ]
    # Nothing brings a deleted listing's work back.
    gate.set()
    client.post(f"/api/batches/{batch_id}/resume")
    assert [r["ai"] for r in _summary(client, batch_id)["rows"]] == ["cancelled", "cancelled"]
    assert provider.count("brief") == 1
    assert _review(client, batch_id, rows[0]["id"]).status_code == 409


def test_cancelling_a_pending_delete_restores_the_row(
    client: TestClient, workspace: Workspace
) -> None:
    """A listing with remotes is only marked ``lifecycle: deleted``;
    Cancel clears the mark before apply, and the listing never went. Its
    row comes back, and a Resume can draft it again."""
    batch_id = _batch(client, "night-hike-club", "cedar-trail")
    _drafted(client, batch_id)
    Lockfile.empty(tool_version="test", applied_at="2026-09-27T12:00:00").model_copy(
        update={"remote": {"printify_product_id": "abc123"}}
    ).write(workspace.lock_file("night-hike-club"))

    pending = client.delete("/api/listings/night-hike-club")
    assert pending.json()["status"] == "pending-delete"
    assert _summary(client, batch_id)["rows"][0]["deleted"] is True

    cancelled = client.patch("/api/listings/night-hike-club", json={"lifecycle": None})
    assert cancelled.status_code == 200, cancelled.text

    row = _summary(client, batch_id)["rows"][0]
    assert (row["deleted"], row["reviewable"]) == (False, True)
    assert client.get("/api/listings/night-hike-club/batch").json()["batch_id"] == batch_id
    # An ordinary edit of a listing nobody deleted touches no row.
    client.patch("/api/listings/cedar-trail", json={"lifecycle": None})
    assert [r["deleted"] for r in _summary(client, batch_id)["rows"]] == [False, False]


# ---------------------------------------------------------- delete batch


def test_deleting_a_batch_record_leaves_every_file_it_made(
    client: TestClient, workspace: Workspace
) -> None:
    batch_id = _batch(client, "night-hike-club")
    _drafted(client, batch_id)
    listing = workspace.listing_file("night-hike-club").read_bytes()

    assert client.delete(f"/api/batches/{batch_id}").status_code == 204

    assert client.get(f"/api/batches/{batch_id}").status_code == 404
    assert all(b["id"] != batch_id for b in client.get("/api/batches").json())
    assert workspace.listing_file("night-hike-club").read_bytes() == listing
    assert workspace.load_listing("night-hike-club").brief != ""
    assert workspace.design_file("night-hike-club").is_file()
    assert ProposalStore(workspace).load("night-hike-club") is not None
    assert client.get("/api/listings/night-hike-club/batch").json() is None


def test_deleting_a_batch_record_cancels_its_work_first(
    client: TestClient, provider: ChainProvider, workspace: Workspace
) -> None:
    provider.gate("brief")
    batch_id = _batch(client, "night-hike-club", "cedar-trail")
    wait_for(lambda: provider.started["brief"].is_set())

    assert client.delete(f"/api/batches/{batch_id}").status_code == 204

    wait_for(lambda: provider.cancelled == ["brief"])
    assert provider.count("brief") == 1
    assert workspace.batch_ids() == []
    assert workspace.listing_file("cedar-trail").is_file()


# ------------------------------------------------------------ cache cleared


def test_clearing_the_cache_loses_the_batches_and_keeps_the_workspace(
    client: TestClient, workspace: Workspace
) -> None:
    """Spec, *Review workflow* and acceptance criterion 10: listing
    templates, designs, listings and accepted copy are the workspace's;
    batches, flags and staging are cache."""
    batch_id = _batch(client, "night-hike-club")
    row = _drafted(client, batch_id)["rows"][0]["id"]
    _review(client, batch_id, row)
    client.post(
        "/api/staging",
        data={"listing_template": LISTING_TEMPLATE},
        files=[("files", ("lake-loop.png", png(9), "image/png"))],
    )
    accepted = client.patch(
        "/api/listings/night-hike-club", json={"etsy": {"title": "Night Hike Club Tee"}}
    )
    assert accepted.status_code == 200, accepted.text

    remove_tree(workspace.cache())

    assert client.get("/api/batches").json() == []
    assert workspace.listing_template_names() == [LISTING_TEMPLATE]
    assert workspace.design_file("night-hike-club").is_file()
    kept = workspace.load_listing("night-hike-club")
    assert kept.etsy.title == "Night Hike Club Tee"
    assert kept.brief != ""


def test_a_listing_removed_outside_the_app_does_not_break_its_batch_summary(
    client: TestClient, workspace: Workspace
) -> None:
    batch_id = _batch(client, "missing-tee")
    row = _drafted(client, batch_id)["rows"][0]
    store = ProposalStore(workspace)
    cached = store.load(row["name"])
    assert cached is not None
    workspace.listing_file(row["name"]).unlink()

    summary = _summary(client, batch_id)

    assert summary["rows"][0]["proposal"] is None
    assert store.load(row["name"]) == cached
