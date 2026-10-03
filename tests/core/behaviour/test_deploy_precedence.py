"""Deploying takes precedence over AI (ADR-0050; spec, *Deployment interaction*;
UI doc §8), with core's two coordinators called directly -- no TestClient
(module-structure plan, PR 9).

A plan or apply for a listing first cancels that listing's AI work --
queued batch rows and any running run, batch or manual -- and waits for the
run to finish before planning reads the listing. While the deploy holds the
listing, a new AI run is refused. The cancelled rows are
``cancelled_by_deploy``: **Resume** leaves them alone, and only a per-row
Retry queues them again, so no proposal lands on a listing after its deploy
unless the seller asks for one.

Both coordinators run, as the UI server runs them -- deployments started
before AI work, AI work stopped first -- because what these pin is how the
two meet. The deploy's context factory is the seam that shows when planning
starts: it is called once the executor has taken the listing, just before
the plan reads it. The fixture workspace has no shop, so a deploy renders
and blocks every other stage -- enough to be a deploy, and nothing here is
about what it deploys. The HTTP mapping of the ``deploying`` refusal is
``tests/server/contract/test_ai_runs_api.py``'s.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pytest

from etsy_listings.core.ai.proposals import ProposalStore
from etsy_listings.core.application import batch_staging, batch_workflow
from etsy_listings.core.application.ai.coordinator import AiCoordinator
from etsy_listings.core.application.ai.registry import AiRun
from etsy_listings.core.application.deploy.deployments import Deployments
from etsy_listings.core.application.deploy.events import TERMINAL_PHASES
from etsy_listings.core.application.deploy.registry import ListingApply, ListingPlan, Run
from etsy_listings.core.application.refusals import ListingDeploying
from etsy_listings.core.application.workspace_locks import WorkspaceLocks
from etsy_listings.core.batches import BatchStore, StagingStore
from etsy_listings.core.clients.printify.fakes import FakeCatalogClient
from etsy_listings.core.engine.context import EventSink, RunContext
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.ai_runs import ChainProvider, has_proposal, seed_prompts, seeded_market, wait_for
from tests.support.batches import LISTING_TEMPLATE, a_listing_template, png, uploads
from tests.support.builders import FIXTURE_LISTING


@dataclass
class Deploys:
    """The executor's context factory, reporting each time a deploy is
    about to read its listings -- and, when ``hold`` is set, holding it
    there until the test lets it go."""

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


class Host:
    """What the UI server holds for one workspace: one of each store and
    lock, and the two coordinators."""

    def __init__(self, workspace: Workspace, provider: ChainProvider, deploys: Deploys) -> None:
        self.workspace = workspace
        self.locks = WorkspaceLocks()
        self.staging = StagingStore(workspace)
        self.batches = BatchStore(workspace)
        market = seeded_market()
        self.ai = AiCoordinator(
            workspace,
            proposals=ProposalStore(workspace),
            batches=self.batches,
            providers=lambda _workspace: [provider],
            market_client=lambda _workspace: market,
        )
        self.deployments = Deployments(workspace, deploys, ai=self.ai)

    def batch(self, *names: str) -> str:
        files = [(f"{name}.png", png(i + 1)) for i, name in enumerate(names)]
        session = batch_staging.stage_upload(
            self.workspace, self.staging, LISTING_TEMPLATE, uploads(*files), locks=self.locks
        )
        batch = batch_workflow.confirm_batch(
            self.workspace,
            self.staging,
            self.batches,
            session.id,
            queue=self.ai.queue,
        )
        return batch.id

    def states(self, batch_id: str) -> list[str | None]:
        batch = batch_workflow.read_batch(self.workspace, self.batches, batch_id)
        return [row.ai for row in batch.rows]

    def deploy(self, kind: Literal["plan", "apply"], listing: str) -> Run:
        command = ListingApply((listing,), {}) if kind == "apply" else ListingPlan((listing,))
        run = self.deployments.submit(command)
        assert isinstance(run, Run), run
        return run

    def resume(self, batch_id: str) -> None:
        batch_workflow.resume_batch(self.workspace, self.batches, batch_id, queue=self.ai.queue)

    def idle(self) -> None:
        assert self.ai.queue.wait_idle(timeout=15)


def _finished(run: Run, *, timeout: float = 20.0) -> str:
    deadline = time.monotonic() + timeout
    while run.phase not in TERMINAL_PHASES:
        if time.monotonic() > deadline:
            pytest.fail(f"run {run.id} never finished (stuck at {run.phase!r})")
        time.sleep(0.02)
    return run.phase


@pytest.fixture
def provider() -> ChainProvider:
    return ChainProvider()


@pytest.fixture
def deploys() -> Deploys:
    return Deploys()


@pytest.fixture
def host(workspace_root: Path, provider: ChainProvider, deploys: Deploys) -> Iterator[Host]:
    seed_prompts(workspace_root)
    workspace = Workspace.discover(root_override=workspace_root)
    a_listing_template(workspace)
    host = Host(workspace, provider, deploys)
    host.deployments.start()
    host.ai.start()
    try:
        yield host
    finally:
        host.ai.stop()
        host.deployments.stop()


def test_an_apply_waits_for_the_running_row_to_stop_and_resume_leaves_it(
    host: Host, provider: ChainProvider, deploys: Deploys
) -> None:
    gate = provider.gate("brief")
    batch_id = host.batch("night-hike-club")
    wait_for(lambda: provider.started["brief"].is_set())
    run = host.ai.registry.latest("night-hike-club")
    assert run is not None
    seen: list[str] = []
    deploys.on_start = lambda: seen.append(run.phase)

    assert _finished(host.deploy("apply", "night-hike-club")) == "applied"

    assert seen == ["cancelled"], "planning read the listing before the AI run had stopped"
    assert provider.cancelled == ["brief"]
    assert host.states(batch_id) == ["cancelled_by_deploy"]

    gate.set()
    host.resume(batch_id)
    host.idle()

    assert host.states(batch_id) == ["cancelled_by_deploy"]
    assert provider.count("brief") == 1


def test_an_apply_cancels_a_queued_row_and_no_proposal_follows_the_deploy(
    host: Host, provider: ChainProvider
) -> None:
    gate = provider.gate("brief")
    batch_id = host.batch("night-hike-club", "cedar-trail")
    wait_for(lambda: provider.started["brief"].is_set())
    assert host.states(batch_id) == ["running", "queued"]

    assert _finished(host.deploy("apply", "cedar-trail")) == "applied"
    assert host.states(batch_id) == ["running", "cancelled_by_deploy"]

    gate.set()
    wait_for(lambda: host.states(batch_id)[0] == "done")
    host.idle()

    assert host.states(batch_id) == ["done", "cancelled_by_deploy"]
    assert not has_proposal(host.workspace.root, "cedar-trail")


@pytest.mark.parametrize("prior_reason", ["cancelled", "timeout"])
def test_deploy_ownership_wins_when_stop_already_requested(
    host: Host,
    provider: ChainProvider,
    prior_reason: Literal["cancelled", "timeout"],
) -> None:
    """ADR-0050 is about who owns the listing, not which stop request won a race:
    Resume must not requeue active work once deploy has claimed it."""
    provider.gate("brief")
    batch_id = host.batch("night-hike-club")
    wait_for(lambda: provider.started["brief"].is_set())
    run = host.ai.registry.latest("night-hike-club")
    assert run is not None

    # Keep the runner from finishing between the seller's cancel request and
    # the deploy's atomic registry hold; Condition uses an RLock, so
    # request_stop itself remains callable while this thread owns it.
    with run.condition:
        assert run.request_stop(prior_reason)
        deploy = host.deploy("apply", "night-hike-club")
        wait_for(lambda: host.ai.registry.deploying("night-hike-club"))
        assert run.stop_reason == prior_reason

    assert _finished(deploy) == "applied"
    assert host.states(batch_id) == ["cancelled_by_deploy"]

    host.resume(batch_id)
    host.idle()
    assert host.states(batch_id) == ["cancelled_by_deploy"]


def test_retry_queues_a_row_the_deploy_cancelled(host: Host, provider: ChainProvider) -> None:
    gate = provider.gate("brief")
    batch_id = host.batch("night-hike-club", "cedar-trail")
    wait_for(lambda: provider.started["brief"].is_set())
    _finished(host.deploy("plan", "cedar-trail"))
    gate.set()
    cedar = batch_workflow.read_batch(host.workspace, host.batches, batch_id).rows[1]

    batch_workflow.retry_batch_row(
        host.workspace,
        host.staging,
        host.batches,
        batch_id,
        cedar.id,
        queue=host.ai.queue,
    )

    wait_for(lambda: host.states(batch_id) == ["done", "done"])
    assert has_proposal(host.workspace.root, "cedar-trail")


def test_a_manual_run_is_stopped_and_a_new_one_refused_while_the_deploy_holds_the_listing(
    host: Host, provider: ChainProvider, deploys: Deploys
) -> None:
    provider.gate("queries")
    started = host.ai.start_run(FIXTURE_LISTING, draft_brief=False)
    assert isinstance(started, AiRun)
    wait_for(lambda: provider.started["queries"].is_set())
    deploys.hold = threading.Event()

    deploy = host.deploy("plan", FIXTURE_LISTING)
    assert deploys.started.wait(15)
    with pytest.raises(ListingDeploying):
        host.ai.start_run(FIXTURE_LISTING, draft_brief=False)
    blocked = host.ai.blocked(FIXTURE_LISTING)
    deploys.hold.set()

    assert isinstance(blocked, ListingDeploying)
    assert (started.phase, provider.cancelled) == ("cancelled", ["queries"])
    assert _finished(deploy) == "ready"
    assert isinstance(host.ai.start_run(FIXTURE_LISTING, draft_brief=False), AiRun)
