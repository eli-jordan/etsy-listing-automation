"""``/api/listings/{name}/proposal``'s HTTP surface (ADR-0049, rename and delete hooks; spec,
*Durable AI proposals*): the cached proposal an AI run wrote, judged stale
against the saved listing, its per-section resolution, and the record
following the listing through rename and delete.

Mapping cases read and resolve a valid saved proposal
(:func:`~tests.support.ai_runs.save_proposal`) through an app whose workers
never start. Generation, replay and cancellation run a real AI run over a
:class:`~tests.support.ai_runs.ChainProvider` and the in-memory market.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from etsy_listings.core.engine.lock import Lockfile
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app

from tests.support.ai_runs import (
    TODAY,
    ChainProvider,
    save_proposal,
    seed_prompts,
    seeded_market,
    wait_for,
)
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
def client(workspace: Workspace) -> TestClient:
    """The HTTP surface alone: no lifespan, so no AI or deploy worker runs."""
    return TestClient(create_app(workspace))


@pytest.fixture
def ai_client(workspace: Workspace, provider: ChainProvider) -> Iterator[TestClient]:
    """A started app whose AI runs answer from ``provider``."""
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


def _saved(workspace: Workspace, **over: Any) -> str:  # noqa: ANN401
    """Saves a valid proposal for the fixture listing; its ``generated_at``."""
    return save_proposal(workspace, LISTING, **over).generated_at.isoformat()


def _resolve(client: TestClient, generated_at: str, **sections: str) -> Any:  # noqa: ANN401
    return client.patch(RESOLUTION, json={"generated_at": generated_at, **sections})


# ---------------------------------------------------------------------- GET


def test_no_proposal_is_404(client: TestClient) -> None:
    assert client.get(PROPOSAL).status_code == 404


def test_an_unknown_listing_is_404(client: TestClient) -> None:
    assert client.get("/api/listings/nope/proposal").status_code == 404


def test_a_run_leaves_its_proposal_current_and_every_section_pending(
    ai_client: TestClient,
) -> None:
    body = _generate(ai_client)

    assert body["proposal"]["titles"][0] == "Retro Sunset Hike Tee"
    assert body["origin"] == "manual"
    assert body["resolution"] == {"title": "pending", "tags": "pending", "lead": "pending"}
    assert body["stale"] == {"is_stale": False, "reasons": []}
    assert set(body) == {"proposal", "snapshot", "generated_at", "origin", "resolution", "stale"}


def test_a_saved_proposal_reads_current_with_its_origin(
    client: TestClient, workspace: Workspace
) -> None:
    _saved(workspace, origin="batch")

    body = client.get(PROPOSAL).json()

    assert body["origin"] == "batch"
    assert body["stale"] == {"is_stale": False, "reasons": []}
    assert body["resolution"] == {"title": "pending", "tags": "pending", "lead": "pending"}


def test_an_edited_brief_makes_it_stale_with_the_reason(
    client: TestClient, workspace: Workspace
) -> None:
    _saved(workspace)

    client.patch(f"/api/listings/{LISTING}", json={"brief": "A different design brief."})

    assert client.get(PROPOSAL).json()["stale"] == {
        "is_stale": True,
        "reasons": ["brief edited since"],
    }


# -------------------------------------------------------------------- PATCH


def test_a_resolution_survives_a_reload(client: TestClient, workspace: Workspace) -> None:
    generated_at = _saved(workspace)

    response = _resolve(client, generated_at, title="accepted", tags="dismissed")

    assert response.status_code == 200
    expected = {"title": "accepted", "tags": "dismissed", "lead": "pending"}
    assert response.json()["resolution"] == expected
    assert client.get(PROPOSAL).json()["resolution"] == expected


def test_a_resolved_section_does_not_reopen_when_the_run_is_replayed(
    ai_client: TestClient,
) -> None:
    """The run's events replay on every reattach, proposal included; what is
    open is the cached record's answer, not the event's."""
    generated_at = _generate(ai_client)["generated_at"]
    _resolve(ai_client, generated_at, title="accepted", tags="accepted", lead="dismissed")

    run = ai_client.get("/api/ai/runs", params={"listing": LISTING}).json()
    events = ai_client.get(f"/api/ai/runs/{run['id']}").json()["events"]

    assert any(event["type"] == "proposal" for event in events)
    assert ai_client.get(PROPOSAL).json()["resolution"] == {
        "title": "accepted",
        "tags": "accepted",
        "lead": "dismissed",
    }


def test_a_section_can_be_reopened(client: TestClient, workspace: Workspace) -> None:
    generated_at = _saved(workspace)
    _resolve(client, generated_at, lead="dismissed")

    assert _resolve(client, generated_at, lead="pending").json()["resolution"]["lead"] == "pending"


def test_resolving_a_regenerated_proposal_is_409(client: TestClient, workspace: Workspace) -> None:
    first = _saved(workspace)
    _saved(workspace, generated_at=TODAY + timedelta(minutes=5))

    response = _resolve(client, first, title="accepted")

    assert response.status_code == 409
    assert client.get(PROPOSAL).json()["resolution"]["title"] == "pending"


def test_resolving_without_a_proposal_is_404(client: TestClient) -> None:
    response = _resolve(client, "2026-09-24T12:00:00Z", title="accepted")

    assert response.status_code == 404


def test_an_unknown_resolution_is_422(client: TestClient, workspace: Workspace) -> None:
    generated_at = _saved(workspace)

    assert _resolve(client, generated_at, title="maybe").status_code == 422
    assert client.get(PROPOSAL).json()["resolution"]["title"] == "pending"


# -------------------------------------------------- rename and delete


def test_renaming_the_listing_moves_its_proposal(client: TestClient, workspace: Workspace) -> None:
    generated_at = _saved(workspace)
    _resolve(client, generated_at, title="accepted")
    before = client.get(PROPOSAL).json()["generated_at"]

    renamed = client.post(f"/api/listings/{LISTING}/rename", json={"new_name": "hike-away"})

    assert renamed.status_code == 200
    moved = client.get("/api/listings/hike-away/proposal")
    assert moved.status_code == 200
    assert moved.json()["generated_at"] == before
    assert moved.json()["resolution"]["title"] == "accepted"
    assert moved.json()["stale"]["is_stale"] is False


def test_a_new_listing_given_the_old_name_has_no_proposal(
    client: TestClient, workspace: Workspace
) -> None:
    _saved(workspace)
    client.post(f"/api/listings/{LISTING}/rename", json={"new_name": "hike-away"})

    document = workspace.listing_file("hike-away").read_text(encoding="utf-8")
    workspace.listing_file(LISTING).parent.mkdir(parents=True)
    workspace.listing_file(LISTING).write_text(document, encoding="utf-8")

    assert client.get(PROPOSAL).status_code == 404


def test_deleting_the_listing_cancels_its_run_before_it_writes_a_proposal(
    ai_client: TestClient, workspace: Workspace, provider: ChainProvider
) -> None:
    client = ai_client
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
