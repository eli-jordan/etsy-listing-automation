"""``/api/listings/{name}/proposal``'s HTTP surface (ADR-0049, rename and delete hooks; spec,
*Durable AI proposals*): the cached proposal an AI run wrote, judged stale
against the saved listing, its per-section resolution, and the record
following the listing through rename and delete.

Proposals are made the way the app makes them, by an AI run over a
:class:`~tests.support.ai_runs.ChainProvider` and the in-memory market.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from etsy_listings.core.engine.lock import Lockfile
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app

from tests.support.ai_runs import ChainProvider, seed_prompts, seeded_market, wait_for
from tests.support.builders import FIXTURE_LISTING as LISTING

PROPOSAL = f"/api/listings/{LISTING}/proposal"
RESOLUTION = f"{PROPOSAL}/resolution"


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    seed_prompts(workspace_root)
    return Workspace.discover(root_override=workspace_root)


@pytest.fixture
def provider() -> ChainProvider:
    return ChainProvider()


@pytest.fixture
def client(workspace: Workspace, provider: ChainProvider) -> Iterator[TestClient]:
    market = seeded_market()
    app = create_app(
        workspace,
        seo_provider_factory=lambda _workspace: [provider],
        market_client_factory=lambda _workspace: market,
    )
    with TestClient(app) as test_client:
        yield test_client


def _generate(client: TestClient, listing: str = LISTING) -> dict[str, Any]:
    started = client.post("/api/ai/runs", json={"listing": listing})
    assert started.status_code == 202, started.text
    deadline = time.monotonic() + 15
    while client.get(f"/api/ai/runs/{started.json()['id']}").json()["phase"] == "running":
        assert time.monotonic() < deadline, "the AI run never finished"
        time.sleep(0.02)
    response = client.get(f"/api/listings/{listing}/proposal")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _resolve(client: TestClient, generated_at: str, **sections: str) -> Any:  # noqa: ANN401
    return client.patch(RESOLUTION, json={"generated_at": generated_at, **sections})


# ---------------------------------------------------------------------- GET


def test_no_proposal_is_404(client: TestClient) -> None:
    assert client.get(PROPOSAL).status_code == 404


def test_an_unknown_listing_is_404(client: TestClient) -> None:
    assert client.get("/api/listings/nope/proposal").status_code == 404


def test_a_run_leaves_its_proposal_current_and_every_section_pending(client: TestClient) -> None:
    body = _generate(client)

    assert body["proposal"]["titles"][0] == "Retro Sunset Hike Tee"
    assert body["origin"] == "manual"
    assert body["resolution"] == {"title": "pending", "tags": "pending", "lead": "pending"}
    assert body["stale"] == {"is_stale": False, "reasons": []}
    assert set(body) == {"proposal", "snapshot", "generated_at", "origin", "resolution", "stale"}


def test_an_edited_brief_makes_it_stale_with_the_reason(client: TestClient) -> None:
    _generate(client)

    client.patch(f"/api/listings/{LISTING}", json={"brief": "A different design brief."})

    assert client.get(PROPOSAL).json()["stale"] == {
        "is_stale": True,
        "reasons": ["brief edited since"],
    }


# -------------------------------------------------------------------- PATCH


def test_a_resolution_survives_a_reload(client: TestClient) -> None:
    generated_at = _generate(client)["generated_at"]

    response = _resolve(client, generated_at, title="accepted", tags="dismissed")

    assert response.status_code == 200
    expected = {"title": "accepted", "tags": "dismissed", "lead": "pending"}
    assert response.json()["resolution"] == expected
    assert client.get(PROPOSAL).json()["resolution"] == expected


def test_a_resolved_section_does_not_reopen_when_the_run_is_replayed(client: TestClient) -> None:
    """The run's events replay on every reattach, proposal included; what is
    open is the cached record's answer, not the event's."""
    generated_at = _generate(client)["generated_at"]
    _resolve(client, generated_at, title="accepted", tags="accepted", lead="dismissed")

    run = client.get("/api/ai/runs", params={"listing": LISTING}).json()
    events = client.get(f"/api/ai/runs/{run['id']}").json()["events"]

    assert any(event["type"] == "proposal" for event in events)
    assert client.get(PROPOSAL).json()["resolution"] == {
        "title": "accepted",
        "tags": "accepted",
        "lead": "dismissed",
    }


def test_a_section_can_be_reopened(client: TestClient) -> None:
    generated_at = _generate(client)["generated_at"]
    _resolve(client, generated_at, lead="dismissed")

    assert _resolve(client, generated_at, lead="pending").json()["resolution"]["lead"] == "pending"


def test_resolving_a_regenerated_proposal_is_409(client: TestClient) -> None:
    first = _generate(client)["generated_at"]
    second = _generate(client)

    response = _resolve(client, first, title="accepted")

    assert response.status_code == 409
    assert client.get(PROPOSAL).json()["resolution"] == second["resolution"]


def test_resolving_without_a_proposal_is_404(client: TestClient) -> None:
    response = _resolve(client, "2026-09-24T12:00:00Z", title="accepted")

    assert response.status_code == 404


def test_an_unknown_resolution_is_422(client: TestClient) -> None:
    generated_at = _generate(client)["generated_at"]

    assert _resolve(client, generated_at, title="maybe").status_code == 422


# -------------------------------------------------- rename and delete


def test_renaming_the_listing_moves_its_proposal(client: TestClient) -> None:
    generated_at = _generate(client)["generated_at"]
    _resolve(client, generated_at, title="accepted")

    renamed = client.post(f"/api/listings/{LISTING}/rename", json={"new_name": "hike-away"})

    assert renamed.status_code == 200
    moved = client.get("/api/listings/hike-away/proposal")
    assert moved.status_code == 200
    assert moved.json()["generated_at"] == generated_at
    assert moved.json()["resolution"]["title"] == "accepted"
    assert moved.json()["stale"]["is_stale"] is False


def test_a_new_listing_given_the_old_name_has_no_proposal(
    client: TestClient, workspace: Workspace
) -> None:
    _generate(client)
    client.post(f"/api/listings/{LISTING}/rename", json={"new_name": "hike-away"})

    document = workspace.listing_file("hike-away").read_text(encoding="utf-8")
    workspace.listing_file(LISTING).parent.mkdir(parents=True)
    workspace.listing_file(LISTING).write_text(document, encoding="utf-8")

    assert client.get(PROPOSAL).status_code == 404


def test_deleting_the_listing_removes_its_proposal(
    client: TestClient, workspace: Workspace
) -> None:
    _generate(client)

    assert client.delete(f"/api/listings/{LISTING}").status_code == 204

    assert not workspace.proposal_file(LISTING).exists()


def test_marking_the_listing_deleted_removes_its_proposal(
    client: TestClient, workspace: Workspace
) -> None:
    """A listing with remotes stays on disk, pending its remote deletion
    ; its proposal goes now, as its market snapshot does."""
    _generate(client)
    Lockfile.empty(tool_version="test", applied_at="2024-01-01T00:00:00").model_copy(
        update={"remote": {"printify_product_id": "abc123"}, "stages_completed": ["render"]}
    ).write(workspace.lock_file(LISTING))

    response = client.delete(f"/api/listings/{LISTING}")

    assert response.status_code == 200
    assert response.json()["status"] == "pending-delete"
    assert client.get(PROPOSAL).status_code == 404


def test_deleting_the_listing_cancels_its_run_before_it_writes_a_proposal(
    client: TestClient, workspace: Workspace, provider: ChainProvider
) -> None:
    Lockfile.empty(tool_version="test", applied_at="2024-01-01T00:00:00").model_copy(
        update={"remote": {"printify_product_id": "abc123"}, "stages_completed": ["render"]}
    ).write(workspace.lock_file(LISTING))
    provider.gate("seo")
    run = client.post("/api/ai/runs", json={"listing": LISTING}).json()
    wait_for(lambda: provider.started["seo"].is_set())

    assert client.delete(f"/api/listings/{LISTING}").status_code == 200

    wait_for(lambda: client.get(f"/api/ai/runs/{run['id']}").json()["phase"] != "running")
    assert client.get(f"/api/ai/runs/{run['id']}").json()["phase"] == "cancelled"
    assert client.get(PROPOSAL).status_code == 404
