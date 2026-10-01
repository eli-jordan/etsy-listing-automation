"""Deploying takes precedence over AI (ADR-0050; spec, *Deployment interaction*;
UI doc §8).

A UI plan or apply for a listing first cancels that listing's AI work --
queued batch rows and any running run, batch or manual -- and waits for the
run to finish before planning reads the listing. While the deploy holds the
listing, a new AI run is refused with ``deploying``. The cancelled rows are
``cancelled_by_deploy``: **Resume** leaves them alone, and only a per-row
Retry queues them again, so no proposal lands on a listing after its deploy
unless the seller asks for one.

Everything goes through the app the seller drives, with the batch queue and
the runs executor both running, because what these pin is how the two meet.
The deploy's context factory is the seam that shows when planning starts:
it is called once the executor has taken the listing, just before the plan
reads it. The fixture workspace has no shop, so a deploy renders and blocks
every other stage -- enough to be a deploy, and nothing here is about what
it deploys.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import pytest
from fastapi.testclient import TestClient

from etsy_listings.core.application.ai.batch_queue import BatchQueue
from etsy_listings.core.clients.printify.fakes import FakeCatalogClient
from etsy_listings.core.engine.context import EventSink, RunContext
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app

from tests.support.ai_runs import ChainProvider, has_proposal, seed_prompts, seeded_market, wait_for
from tests.support.batches import LISTING_TEMPLATE, a_listing_template, png


@dataclass
class Deploys:
    """The executor's context factory, reporting each time a deploy is
    about to read its listings -- and, when ``hold`` is set, holding it
    there until the test lets it go."""

    workspace: Workspace
    on_start: Callable[[], None] | None = None
    hold: threading.Event | None = None
    started: threading.Event = field(default_factory=threading.Event)

    def __call__(self, workspace: Workspace, on_event: EventSink | None) -> RunContext:
        if self.on_start is not None:
            self.on_start()
        self.started.set()
        if self.hold is not None:
            assert self.hold.wait(15)
        sink = {"on_event": on_event} if on_event is not None else {}
        return RunContext(workspace=workspace, catalog=FakeCatalogClient([], {}, {}), **sink)


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
def deploys(workspace: Workspace) -> Deploys:
    return Deploys(workspace)


@pytest.fixture
def client(workspace: Workspace, provider: ChainProvider, deploys: Deploys) -> Iterator[TestClient]:
    market = seeded_market()
    app = create_app(
        workspace,
        context_factory=deploys,
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


def _rows(client: TestClient, batch_id: str) -> list[dict[str, Any]]:
    response = client.get(f"/api/batches/{batch_id}")
    assert response.status_code == 200, response.text
    rows: list[dict[str, Any]] = response.json()["rows"]
    return rows


def _states(client: TestClient, batch_id: str) -> list[str | None]:
    return [row["ai"] for row in _rows(client, batch_id)]


def _deploy(client: TestClient, kind: str, listing: str) -> str:
    body: dict[str, Any] = {"kind": kind, "scope": "listings", "listings": [listing]}
    if kind == "apply":
        body["expect"] = {}
    response = client.post("/api/runs", json=body)
    assert response.status_code == 202, response.text
    run_id: str = response.json()["id"]
    return run_id


def _finished(client: TestClient, run_id: str) -> str:
    terminal = {"ready", "applied", "failed", "stale", "cancelled"}
    wait_for(lambda: client.get(f"/api/runs/{run_id}").json()["phase"] in terminal)
    phase: str = client.get(f"/api/runs/{run_id}").json()["phase"]
    return phase


def _queue(client: TestClient) -> BatchQueue:
    queue: BatchQueue = client.app.state.batch_queue  # type: ignore[attr-defined]
    return queue


def _idle(client: TestClient) -> None:
    assert _queue(client).wait_idle(timeout=15)


def test_an_apply_waits_for_the_running_row_to_stop_and_resume_leaves_it(
    client: TestClient, provider: ChainProvider, deploys: Deploys
) -> None:
    gate = provider.gate("brief")
    batch_id = _batch(client, "night-hike-club")
    wait_for(lambda: provider.started["brief"].is_set())
    run = client.app.state.ai_run_registry.latest("night-hike-club")  # type: ignore[attr-defined]
    seen: list[str] = []
    deploys.on_start = lambda: seen.append(run.phase)

    assert _finished(client, _deploy(client, "apply", "night-hike-club")) == "applied"

    assert seen == ["cancelled"], "planning read the listing before the AI run had stopped"
    assert provider.cancelled == ["brief"]
    assert _states(client, batch_id) == ["cancelled_by_deploy"]

    gate.set()
    client.post(f"/api/batches/{batch_id}/resume")
    _idle(client)

    assert _states(client, batch_id) == ["cancelled_by_deploy"]
    assert provider.count("brief") == 1


def test_an_apply_cancels_a_queued_row_and_no_proposal_follows_the_deploy(
    client: TestClient, provider: ChainProvider
) -> None:
    gate = provider.gate("brief")
    batch_id = _batch(client, "night-hike-club", "cedar-trail")
    wait_for(lambda: provider.started["brief"].is_set())
    assert _states(client, batch_id) == ["running", "queued"]

    assert _finished(client, _deploy(client, "apply", "cedar-trail")) == "applied"
    assert _states(client, batch_id) == ["running", "cancelled_by_deploy"]

    gate.set()
    wait_for(lambda: _states(client, batch_id)[0] == "done")
    _idle(client)

    assert _states(client, batch_id) == ["done", "cancelled_by_deploy"]
    assert not has_proposal(client.app.state.workspace.root, "cedar-trail")  # type: ignore[attr-defined]


@pytest.mark.parametrize("prior_reason", ["cancelled", "timeout"])
def test_deploy_ownership_wins_when_stop_already_requested(
    client: TestClient,
    provider: ChainProvider,
    prior_reason: Literal["cancelled", "timeout"],
) -> None:
    """ADR-0050 is about who owns the listing, not which stop request won a race:
    Resume must not requeue active work once deploy has claimed it."""
    provider.gate("brief")
    batch_id = _batch(client, "night-hike-club")
    wait_for(lambda: provider.started["brief"].is_set())
    registry = client.app.state.ai_run_registry  # type: ignore[attr-defined]
    run = registry.latest("night-hike-club")
    assert run is not None

    # Keep the runner from finishing between the seller's cancel request and
    # the deploy's atomic registry hold; Condition uses an RLock, so
    # request_stop itself remains callable while this thread owns it.
    with run.condition:
        assert run.request_stop(prior_reason)
        deploy_id = _deploy(client, "apply", "night-hike-club")
        wait_for(lambda: registry.deploying("night-hike-club"))
        assert run.stop_reason == prior_reason

    assert _finished(client, deploy_id) == "applied"
    assert _states(client, batch_id) == ["cancelled_by_deploy"]

    client.post(f"/api/batches/{batch_id}/resume")
    _idle(client)
    assert _states(client, batch_id) == ["cancelled_by_deploy"]


def test_retry_queues_a_row_the_deploy_cancelled(
    client: TestClient, provider: ChainProvider
) -> None:
    gate = provider.gate("brief")
    batch_id = _batch(client, "night-hike-club", "cedar-trail")
    wait_for(lambda: provider.started["brief"].is_set())
    _finished(client, _deploy(client, "plan", "cedar-trail"))
    gate.set()
    cedar = _rows(client, batch_id)[1]

    retried = client.post(f"/api/batches/{batch_id}/rows/{cedar['id']}/retry")

    assert retried.status_code == 200, retried.text
    wait_for(lambda: _states(client, batch_id) == ["done", "done"])
    assert has_proposal(client.app.state.workspace.root, "cedar-trail")  # type: ignore[attr-defined]


def test_a_manual_run_is_stopped_and_a_new_one_refused_while_the_deploy_holds_the_listing(
    client: TestClient, provider: ChainProvider, deploys: Deploys
) -> None:
    provider.gate("queries")
    started = client.post("/api/ai/runs", json={"listing": "take-a-hike", "draft_brief": False})
    assert started.status_code == 202, started.text
    wait_for(lambda: provider.started["queries"].is_set())
    deploys.hold = threading.Event()

    run_id = _deploy(client, "plan", "take-a-hike")
    assert deploys.started.wait(15)
    refused = client.post("/api/ai/runs", json={"listing": "take-a-hike", "draft_brief": False})
    readiness = client.get("/api/listings/take-a-hike/ai-seo/readiness").json()
    deploys.hold.set()

    assert refused.status_code == 409
    assert refused.json()["reason"] == "deploying"
    assert readiness["ready"] is False
    assert readiness["deploying"] is True
    assert provider.cancelled == ["queries"]
    assert _finished(client, run_id) == "ready"
    again = client.post("/api/ai/runs", json={"listing": "take-a-hike", "draft_brief": False})
    assert again.status_code == 202, again.text
