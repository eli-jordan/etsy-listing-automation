"""``core/application/deploy/deployments.py``: deployment coordination called
directly -- no FastAPI, no TestClient (module-structure plan, PR 8).

Conflicts, the exact reviewed set a workspace apply must name (ADR-0042),
FIFO execution and the deploy-to-AI handoff (ADR-0041, ADR-0050),
retention, cancellation, shutdown and replay after an event id. The HTTP
mapping of each answer stays in ``tests/contract/test_runs_api.py``.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from etsy_listings.core.ai.proposals import ProposalStore
from etsy_listings.core.application.ai.coordinator import AiCoordinator
from etsy_listings.core.application.deploy.deployments import Deployments
from etsy_listings.core.application.deploy.events import (
    TERMINAL_PHASES,
    ListingPlannedEvent,
    PlanDTO,
    StageCheckingEvent,
)
from etsy_listings.core.application.deploy.registry import (
    Conflict,
    ListingApply,
    ListingPlan,
    Run,
    WorkspaceApply,
    WorkspacePlan,
)
from etsy_listings.core.application.refusals import ReviewedPlanRefused
from etsy_listings.core.application.workspace_locks import WorkspaceLocks
from etsy_listings.core.batches import BatchStore
from etsy_listings.core.clients.printify.fakes import FakeCatalogClient
from etsy_listings.core.engine.context import EventSink, RunContext
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import copy_listing

FINGERPRINT = "sha256:" + "1" * 64


def _context(workspace: Workspace, on_event: EventSink | None = None) -> RunContext:
    """No shop configured: only ``render`` has work, which is enough to run
    every phase without a client."""
    kwargs = {"on_event": on_event} if on_event is not None else {}
    return RunContext(
        workspace=workspace,
        catalog=FakeCatalogClient([], {}, {}),
        printify=None,
        etsy=None,
        **kwargs,
    )


def _wait_until_terminal(run: Run, *, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if run.phase in TERMINAL_PHASES:
            return
        time.sleep(0.02)
    pytest.fail(f"run {run.id} never reached a terminal phase (stuck at {run.phase!r})")


def _run(result: Run | Conflict) -> Run:
    assert isinstance(result, Run), result
    return result


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


@pytest.fixture
def idle(workspace: Workspace) -> Deployments:
    """Never started: runs queue and nothing executes them."""
    return Deployments(workspace, _context)


def _reviewed_workspace_plan(deployments: Deployments, *listings: str) -> Run:
    """A ready workspace plan that reviewed ``listings``, each at
    :data:`FINGERPRINT`, without executing it."""
    run = _run(deployments.submit(WorkspacePlan(listings)))
    run.transition_plan("planning")
    for name in listings:
        plan = PlanDTO(listing=name, is_live=False, etsy_listing_id=None, stage_plans=())
        run.append(
            lambda i, name=name, plan=plan: ListingPlannedEvent(
                id=i, listing=name, plan=plan, fingerprint=FINGERPRINT
            )
        )
    run.transition_plan("planned")
    run.transition_plan("ready")
    return run


# ------------------------------------------------------------------ lifetime


def test_construction_starts_no_thread_and_runs_wait_for_start(
    workspace: Workspace,
) -> None:
    before = {thread.name for thread in threading.enumerate()}

    deployments = Deployments(workspace, _context)
    run = _run(deployments.submit(ListingPlan((LISTING,))))
    time.sleep(0.2)

    assert {thread.name for thread in threading.enumerate()} == before
    assert run.phase == "queued"

    deployments.start()
    try:
        _wait_until_terminal(run)
    finally:
        deployments.stop()
    assert run.phase == "ready"


# ----------------------------------------------------------------- conflicts


def test_a_run_for_a_listing_already_in_flight_is_a_conflict_naming_it(
    idle: Deployments,
) -> None:
    first = _run(idle.submit(ListingPlan((LISTING,))))

    second = idle.submit(ListingApply((LISTING,), {LISTING: FINGERPRINT}))

    assert second == Conflict(active_run=first.id)


def test_a_workspace_run_conflicts_with_an_active_listing_run(idle: Deployments) -> None:
    first = _run(idle.submit(ListingPlan((LISTING,))))

    assert idle.submit(WorkspacePlan((LISTING,))) == Conflict(active_run=first.id)


# -------------------------------------------------------- the reviewed set


def test_a_workspace_apply_naming_exactly_the_reviewed_set_is_queued(idle: Deployments) -> None:
    reviewed = _reviewed_workspace_plan(idle, "a", "b")

    run = _run(
        idle.submit(WorkspaceApply(("a", "b"), {"a": FINGERPRINT, "b": FINGERPRINT}, reviewed.id))
    )

    assert run.reviewed_run_id == reviewed.id
    assert run.phase == "queued"


@pytest.mark.parametrize(
    ("listings", "expect", "message"),
    [
        (
            ("a",),
            {"a": FINGERPRINT},
            "apply listings must exactly match the reviewed workspace plan",
        ),
        (
            ("a", "b", "c"),
            {"a": FINGERPRINT, "b": FINGERPRINT, "c": FINGERPRINT},
            "apply listings must exactly match the reviewed workspace plan",
        ),
        (("b", "a"), {"a": FINGERPRINT, "b": FINGERPRINT}, "apply listings must exactly match"),
        (
            ("a", "b"),
            {"a": FINGERPRINT, "b": "sha256:" + "0" * 64},
            "apply fingerprints must exactly match the reviewed workspace plan",
        ),
        (("a", "b"), {"a": FINGERPRINT}, "apply fingerprints must exactly match"),
    ],
    ids=["omitted", "added", "reordered", "fingerprint", "missing-fingerprint"],
)
def test_a_workspace_apply_differing_from_the_reviewed_set_is_refused(
    idle: Deployments, listings: tuple[str, ...], expect: dict[str, str], message: str
) -> None:
    reviewed = _reviewed_workspace_plan(idle, "a", "b")

    with pytest.raises(ReviewedPlanRefused, match=message):
        idle.submit(WorkspaceApply(listings, expect, reviewed.id))

    assert idle.runs(scope="workspace") == [reviewed], "a refusal queues nothing"


def test_a_workspace_apply_needs_a_ready_review(idle: Deployments) -> None:
    queued = _run(idle.submit(WorkspacePlan(("a",))))

    with pytest.raises(ReviewedPlanRefused, match="reviewed workspace plan is not ready"):
        idle.submit(WorkspaceApply((), {}, queued.id))


@pytest.mark.parametrize("source", ["missing", "listing-plan", "apply"])
def test_a_workspace_apply_needs_a_workspace_plan_as_its_review(
    idle: Deployments, source: str
) -> None:
    if source == "missing":
        reviewed_id = "missing-review"
    elif source == "listing-plan":
        reviewed_id = _run(idle.submit(ListingPlan(("a",)))).id
    else:
        reviewed_id = _run(idle.submit(ListingApply(("a",), {"a": FINGERPRINT}))).id

    with pytest.raises(ReviewedPlanRefused, match="reviewed_run_id is not a workspace plan"):
        idle.submit(WorkspaceApply((), {}, reviewed_id))


# ------------------------------------------------------------------ retention


def test_a_finished_run_answers_for_its_listing_until_the_next_run_supersedes_it(
    idle: Deployments,
) -> None:
    first = _run(idle.submit(ListingPlan((LISTING,))))
    first.transition_plan("cancelled")

    assert idle.runs(listing=LISTING) == [first]

    second = _run(idle.submit(ListingPlan((LISTING,))))

    assert idle.runs(listing=LISTING) == [second]
    assert idle.get(first.id) is first, "superseded, but still answers by id"


def test_the_review_stays_retained_beside_the_apply_that_names_it(idle: Deployments) -> None:
    reviewed = _reviewed_workspace_plan(idle, "a")

    applied = _run(idle.submit(WorkspaceApply(("a",), {"a": FINGERPRINT}, reviewed.id)))

    assert idle.runs(scope="workspace") == [applied]
    assert idle.get(reviewed.id) is reviewed
    assert reviewed.phase == "ready"


def test_runs_with_no_filter_are_every_run_remembered(idle: Deployments) -> None:
    a = _run(idle.submit(ListingPlan(("a",))))
    b = _run(idle.submit(ListingPlan(("b",))))

    assert idle.runs() == [a, b]
    assert idle.runs(scope="listings") == [a, b]
    assert idle.runs(listing="never-touched") == []


# ------------------------------------------------------------ FIFO and handoff


def test_runs_execute_one_at_a_time_in_the_order_queued_after_yielding_ai_work(
    workspace_root: Path, workspace: Workspace
) -> None:
    """ADR-0041's single worker, and ADR-0050's precedence: each run takes
    its listings from AI work before reading them and holds them until it
    ends."""
    copy_listing(workspace_root, "second")
    ai = AiCoordinator(
        workspace,
        locks=WorkspaceLocks(),
        proposals=ProposalStore(workspace),
        batches=BatchStore(workspace),
        providers=lambda _workspace: [],
        market_client=lambda _workspace: None,
    )
    held: list[tuple[bool, bool]] = []

    def context(workspace: Workspace, on_event: EventSink | None = None) -> RunContext:
        """Called as a run is about to read its listings: which of the two
        does AI work have to leave alone right now?"""
        held.append((ai.registry.deploying(LISTING), ai.registry.deploying("second")))
        return _context(workspace, on_event)

    deployments = Deployments(workspace, context, ai=ai)
    first = _run(deployments.submit(ListingApply((LISTING,), {})))
    second = _run(deployments.submit(ListingPlan(("second",))))
    deployments.start()
    try:
        _wait_until_terminal(first)
        _wait_until_terminal(second)
    finally:
        deployments.stop()

    assert held == [(True, False), (False, True)]
    assert not ai.registry.deploying(LISTING) and not ai.registry.deploying("second")
    assert (first.phase, second.phase) == ("applied", "ready")


# --------------------------------------------------------------- cancellation


def test_an_apply_cannot_be_cancelled(idle: Deployments) -> None:
    run = _run(idle.submit(ListingApply((LISTING,), {})))

    assert idle.cancel(run.id) is False
    assert run.phase == "queued"


def test_cancel_answers_none_for_an_unknown_run(idle: Deployments) -> None:
    assert idle.cancel("no-such-run") is None


def test_a_queued_plan_is_cancelled_outright(idle: Deployments) -> None:
    run = _run(idle.submit(ListingPlan((LISTING,))))

    assert idle.cancel(run.id) is True
    assert run.phase == "cancelled"
    assert idle.cancel(run.id) is False, "a finished run cannot be cancelled again"


def test_a_planning_run_stops_before_its_next_listing(
    workspace_root: Path, workspace: Workspace
) -> None:
    """Cancelling is honoured at the engine's safe points -- here, before
    the first listing's plan starts -- not by interrupting one."""
    copy_listing(workspace_root, "second")
    planning = threading.Event()
    cancelled = threading.Event()

    def gated(ws: Workspace, on_event: EventSink | None) -> RunContext:
        planning.set()
        assert cancelled.wait(timeout=10)
        return _context(ws, on_event)

    deployments = Deployments(workspace, gated)
    run = _run(deployments.submit(ListingPlan((LISTING, "second"))))
    deployments.start()
    try:
        assert planning.wait(timeout=10)
        assert run.phase == "planning"
        assert deployments.cancel(run.id) is True
        assert run.phase == "planning", "a running plan is asked, not forced"
        cancelled.set()
        _wait_until_terminal(run)
    finally:
        deployments.stop()

    assert run.phase == "cancelled"
    assert not [event for event in run.events if isinstance(event, StageCheckingEvent)]


# ------------------------------------------------------------------- shutdown


def test_stop_finishes_the_work_in_flight_keeps_its_progress_and_starts_nothing_else(
    workspace_root: Path, workspace: Workspace
) -> None:
    """Shutdown (ADR-0041): the stage in progress finishes and its lockfile
    entry is kept (ADR-0037); the apply's next listing and every queued run
    never start -- a queued plan is cancelled, a queued apply fails."""
    copy_listing(workspace_root, "second")
    copy_listing(workspace_root, "third")
    copy_listing(workspace_root, "fourth")
    in_flight = threading.Event()
    stopping = threading.Event()

    def stalls_first_progress(ws: Workspace, on_event: EventSink | None) -> RunContext:
        def sink(event: object) -> None:
            if not in_flight.is_set():
                in_flight.set()
                assert stopping.wait(timeout=10)

        return _context(ws, sink)

    assert not workspace.lock_file(LISTING).exists()
    deployments = Deployments(workspace, stalls_first_progress)
    applying = _run(deployments.submit(ListingApply((LISTING, "second"), {})))
    queued_plan = _run(deployments.submit(ListingPlan(("third",))))
    queued_apply = _run(deployments.submit(ListingApply(("fourth",), {})))
    deployments.start()
    assert in_flight.wait(timeout=10)

    stopper = threading.Thread(target=deployments.stop)
    stopper.start()
    deadline = time.monotonic() + 10
    while queued_plan.phase != "cancelled" and time.monotonic() < deadline:
        time.sleep(0.01)
    stopping.set()
    stopper.join(timeout=30)

    assert not stopper.is_alive()
    assert applying.phase in TERMINAL_PHASES
    assert workspace.lock_file(LISTING).exists(), "the finished stage's progress is kept"
    assert not workspace.lock_file("second").exists()
    started = {getattr(event, "listing", None) for event in applying.events}
    assert "second" not in started
    assert queued_plan.phase == "cancelled"
    assert queued_apply.phase == "failed"
    assert [event.type for event in queued_apply.events] == ["phase", "phase"]


# --------------------------------------------------------------------- replay


def test_waiting_after_an_event_id_replays_what_followed_in_order_then_blocks(
    idle: Deployments,
) -> None:
    run = _run(idle.submit(ListingPlan((LISTING,))))
    run.transition_plan("planning")
    for stage in ("render", "publish", "etsy_listing"):
        run.append(lambda i, stage=stage: StageCheckingEvent(id=i, listing=LISTING, stage=stage))
    last_seen = run.events[2].id

    replayed, done = run.wait_for_events(last_seen, timeout=0.01)

    assert [event.id for event in replayed] == [last_seen + 1, last_seen + 2]
    assert [event.stage for event in replayed if isinstance(event, StageCheckingEvent)] == [
        "publish",
        "etsy_listing",
    ]
    assert not done

    waited: list[list[int]] = []
    waiter = threading.Thread(
        target=lambda: waited.append(
            [e.id for e in run.wait_for_events(run.events[-1].id, timeout=10)[0]]
        )
    )
    waiter.start()
    time.sleep(0.1)
    run.transition_plan("cancelled")
    waiter.join(timeout=10)

    assert waited == [[run.events[-1].id]]
    rest, done = run.wait_for_events(run.events[-1].id, timeout=0.01)
    assert (rest, done) == ([], True)
