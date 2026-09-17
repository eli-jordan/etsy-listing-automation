"""``ui/runs/registry.py`` (A33, decision 7): per-listing locks, FIFO
queueing, cancellation and retention -- all pure state, no executor and no
workspace, which is what makes this a unit-layer file rather than a
behaviour one.
"""

from __future__ import annotations

from etsy_listings.ui.runs.registry import Conflict, Run, RunRegistry


def _registry() -> RunRegistry:
    ids = iter(f"run-{i}" for i in range(1, 1000))
    return RunRegistry(_id_source=lambda: next(ids))


# --------------------------------------------------------------------- create


def test_create_returns_a_queued_run() -> None:
    registry = _registry()

    run = registry.create("plan", ["take-a-hike"])

    assert isinstance(run, Run)
    assert run.phase == "queued"
    assert run.listings == ("take-a-hike",)
    assert run.events[0].type == "phase"
    assert run.events[0].phase == "queued"


def test_a_second_run_for_the_same_listing_is_refused_while_the_first_is_active() -> None:
    registry = _registry()
    first = registry.create("plan", ["take-a-hike"])
    assert isinstance(first, Run)

    second = registry.create("apply", ["take-a-hike"])

    assert isinstance(second, Conflict)
    assert second.active_run == first.id


def test_a_run_for_a_different_listing_is_not_refused() -> None:
    registry = _registry()
    registry.create("plan", ["take-a-hike"])

    second = registry.create("plan", ["another-one"])

    assert isinstance(second, Run)


def test_a_run_naming_several_listings_locks_every_one() -> None:
    registry = _registry()
    registry.create("plan", ["a", "b"])

    conflict = registry.create("plan", ["b", "c"])

    assert isinstance(conflict, Conflict)


def test_a_finished_run_does_not_block_a_new_one_for_the_same_listing() -> None:
    registry = _registry()
    first = registry.create("plan", ["take-a-hike"])
    assert isinstance(first, Run)
    first.transition("ready")

    second = registry.create("plan", ["take-a-hike"])

    assert isinstance(second, Run)
    assert second.id != first.id


# ----------------------------------------------------------------------- get


def test_get_returns_none_for_an_unknown_id() -> None:
    assert _registry().get("nope") is None


def test_get_returns_the_run_by_id() -> None:
    registry = _registry()
    run = registry.create("plan", ["take-a-hike"])
    assert isinstance(run, Run)

    assert registry.get(run.id) is run


# ----------------------------------------------------------------- for_listing


def test_for_listing_is_empty_for_a_never_touched_listing() -> None:
    assert _registry().for_listing("take-a-hike") == []


def test_for_listing_returns_the_current_holder_active_or_finished() -> None:
    registry = _registry()
    run = registry.create("plan", ["take-a-hike"])
    assert isinstance(run, Run)

    assert registry.for_listing("take-a-hike") == [run]

    run.transition("ready")
    assert registry.for_listing("take-a-hike") == [run], "retention: kept until superseded"


def test_for_listing_moves_on_once_a_new_run_is_created() -> None:
    registry = _registry()
    first = registry.create("plan", ["take-a-hike"])
    assert isinstance(first, Run)
    first.transition("ready")

    second = registry.create("apply", ["take-a-hike"])
    assert isinstance(second, Run)

    assert registry.for_listing("take-a-hike") == [second]


# -------------------------------------------------------------------- dequeue


def test_dequeue_returns_ids_in_fifo_order() -> None:
    registry = _registry()
    first = registry.create("plan", ["a"])
    second = registry.create("plan", ["b"])
    assert isinstance(first, Run)
    assert isinstance(second, Run)

    assert registry.dequeue(timeout=0.1) == first.id
    assert registry.dequeue(timeout=0.1) == second.id


def test_dequeue_times_out_to_none_on_an_empty_queue() -> None:
    assert _registry().dequeue(timeout=0.05) is None


# -------------------------------------------------------------- drain_and_cancel


def test_drain_and_cancel_cancels_every_queued_run() -> None:
    registry = _registry()
    plan_run = registry.create("plan", ["a"])
    apply_run = registry.create("apply", ["b"])
    assert isinstance(plan_run, Run)
    assert isinstance(apply_run, Run)

    registry.drain_and_cancel()

    assert plan_run.phase == "cancelled"
    assert apply_run.phase == "cancelled", "a queued apply that never started is fair game too"
    assert registry.dequeue(timeout=0.05) is None, "the queue is now empty"


def test_drain_and_cancel_leaves_an_already_dequeued_run_alone() -> None:
    registry = _registry()
    run = registry.create("plan", ["a"])
    assert isinstance(run, Run)
    registry.dequeue(timeout=0.1)  # the worker thread "picked it up"
    run.transition("planning")

    registry.drain_and_cancel()

    assert run.phase == "planning"


# ------------------------------------------------------------------------ cancel


def test_cancel_an_unknown_run_returns_none() -> None:
    assert _registry().cancel("nope") is None


def test_cancel_an_apply_is_refused() -> None:
    registry = _registry()
    run = registry.create("apply", ["take-a-hike"])
    assert isinstance(run, Run)

    assert registry.cancel(run.id) is False
    assert run.phase == "queued", "refused, not cancelled"


def test_cancel_a_queued_plan_cancels_it_immediately() -> None:
    registry = _registry()
    run = registry.create("plan", ["take-a-hike"])
    assert isinstance(run, Run)

    assert registry.cancel(run.id) is True
    assert run.phase == "cancelled"


def test_cancel_a_planning_run_asks_it_to_stop_without_forcing_the_phase() -> None:
    """Only the worker thread executing it can safely move it to
    ``cancelled`` -- this only raises the flag `executor.py` checks."""
    registry = _registry()
    run = registry.create("plan", ["take-a-hike"])
    assert isinstance(run, Run)
    run.transition("planning")

    assert registry.cancel(run.id) is True
    assert run.phase == "planning"
    assert run.cancel_requested is True


def test_cancel_an_already_finished_run_is_refused() -> None:
    registry = _registry()
    run = registry.create("plan", ["take-a-hike"])
    assert isinstance(run, Run)
    run.transition("ready")

    assert registry.cancel(run.id) is False


# ------------------------------------------------------------------------- Run


def test_append_assigns_increasing_ids_after_the_initial_phase_event() -> None:
    from etsy_listings.ui.runs.events import StageCheckingEvent

    run = Run(id="r1", kind="plan", listings=("take-a-hike",))

    first = run.append(lambda i: StageCheckingEvent(id=i, listing="take-a-hike", stage="render"))
    second = run.append(lambda i: StageCheckingEvent(id=i, listing="take-a-hike", stage="publish"))

    assert (first.id, second.id) == (2, 3)


def test_wait_for_events_returns_immediately_when_events_are_already_pending() -> None:
    from etsy_listings.ui.runs.events import StageCheckingEvent

    run = Run(id="r1", kind="plan", listings=("take-a-hike",))
    run.append(lambda i: StageCheckingEvent(id=i, listing="take-a-hike", stage="render"))

    pending, done = run.wait_for_events(0, timeout=0.01)

    assert len(pending) == 2, "the initial `queued` phase event is pending too"
    assert done is False


def test_wait_for_events_reports_done_once_terminal_and_drained() -> None:
    run = Run(id="r1", kind="plan", listings=("take-a-hike",))
    run.transition("ready")

    pending, done = run.wait_for_events(run.events[-1].id, timeout=0.01)

    assert pending == []
    assert done is True


def test_wait_for_events_times_out_without_being_done() -> None:
    run = Run(id="r1", kind="plan", listings=("take-a-hike",))

    pending, done = run.wait_for_events(run.events[-1].id, timeout=0.01)

    assert pending == []
    assert done is False


def test_mark_seen() -> None:
    run = Run(id="r1", kind="apply", listings=("take-a-hike",))
    assert run.seen is False

    run.mark_seen()

    assert run.seen is True
