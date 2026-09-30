"""``server/airuns/registry.py`` (market-seo implementation plan, PR 5): one
active AI run per listing, the latest run kept until the next replaces it,
and each run's event buffer -- pure state, no thread and no workspace.
"""

from __future__ import annotations

import threading

from etsy_listings.server.airuns.registry import AiRun, AiRunRegistry, Conflict, Deploying


def _registry() -> AiRunRegistry:
    ids = iter(f"ai-{i}" for i in range(1, 1000))
    return AiRunRegistry(id_source=lambda: next(ids))


def _create(registry: AiRunRegistry, listing: str = "take-a-hike") -> AiRun:
    run = registry.create(listing, draft_brief=False)
    assert isinstance(run, AiRun)
    return run


def test_create_claims_the_listing_with_a_running_run() -> None:
    registry = _registry()

    run = _create(registry)

    assert run.listing == "take-a-hike"
    assert run.phase == "running"
    assert run.events == []
    assert registry.latest("take-a-hike") is run
    assert registry.get(run.id) is run


def test_a_second_run_for_an_active_listing_is_refused_naming_the_active_run() -> None:
    registry = _registry()
    first = _create(registry)

    second = registry.create("take-a-hike", draft_brief=True)

    assert second == Conflict(active_run=first.id)
    assert registry.latest("take-a-hike") is first


def test_listing_names_are_claimed_case_insensitively() -> None:
    registry = _registry()
    first = _create(registry, "Take-A-Hike")

    assert registry.create("take-a-hike", draft_brief=False) == Conflict(active_run=first.id)
    assert registry.latest("TAKE-A-HIKE") is first


def test_another_listing_is_not_refused() -> None:
    registry = _registry()
    _create(registry, "take-a-hike")

    assert isinstance(registry.create("sunset", draft_brief=False), AiRun)


def test_a_finished_run_is_kept_until_the_next_run_replaces_it() -> None:
    registry = _registry()
    first = _create(registry)
    first.finish("done")

    assert registry.latest("take-a-hike") is first
    second = _create(registry)

    assert registry.latest("take-a-hike") is second
    assert registry.get(first.id) is None


def test_active_lists_only_runs_that_have_not_finished() -> None:
    registry = _registry()
    running = _create(registry, "take-a-hike")
    _create(registry, "sunset").finish("failed", "boom")

    assert registry.active() == [running]


def test_steps_reflect_the_latest_step_event_for_each_node() -> None:
    run = _create(_registry())

    run.step("brief", "skipped", "You wrote the brief, so it was kept")
    run.step("market", "pending")
    run.step("seo", "pending")
    run.step("market", "active", "Choosing Etsy searches from the brief")

    assert [(s.id, s.state, s.detail) for s in run.steps] == [
        ("brief", "skipped", "You wrote the brief, so it was kept"),
        ("market", "active", "Choosing Etsy searches from the brief"),
        ("seo", "pending", None),
    ]
    assert [event.seq for event in run.events] == [1, 2, 3, 4]
    assert run.active_step == "market"


def test_finish_emits_one_terminal_phase_event_and_ignores_a_second() -> None:
    run = _create(_registry())

    run.finish("failed", "Etsy market search failed: 503")
    run.finish("done")

    assert run.phase == "failed"
    assert run.finished_at is not None
    phases = [event for event in run.events if event.type == "phase"]
    assert len(phases) == 1
    assert phases[0].message == "Etsy market search failed: 503"


def test_request_stop_sets_the_cancel_event_and_keeps_the_first_reason() -> None:
    run = _create(_registry())

    assert run.request_stop("cancelled") is True
    assert run.request_stop("timeout") is True

    assert run.cancel_event.is_set()
    assert run.stop_reason == "cancelled"


def test_request_stop_refuses_a_finished_run() -> None:
    run = _create(_registry())
    run.finish("done")

    assert run.request_stop("cancelled") is False
    assert not run.cancel_event.is_set()


def test_wait_for_events_returns_what_came_after_and_done_once_finished() -> None:
    run = _create(_registry())
    run.step("brief", "skipped")
    run.step("market", "pending")

    pending, done = run.wait_for_events(1, timeout=0.01)
    assert [event.seq for event in pending] == [2]
    assert done is False

    run.finish("done")
    pending, done = run.wait_for_events(2, timeout=0.01)
    assert [event.type for event in pending] == ["phase"]
    assert done is False

    pending, done = run.wait_for_events(3, timeout=0.01)
    assert pending == []
    assert done is True


def test_forgetting_a_listing_drops_its_finished_run() -> None:
    # A deleted or renamed listing's old run must not be what a new listing
    # of that name reattaches to -- its replayed brief and proposal belong
    # to a listing that no longer exists.
    registry = _registry()
    run = _create(registry, "Take-A-Hike")
    run.finish("done")

    registry.forget("take-a-hike")

    assert registry.latest("take-a-hike") is None
    assert registry.get(run.id) is None


def test_forgetting_a_listing_leaves_a_running_run_to_end_on_its_own() -> None:
    registry = _registry()
    run = _create(registry)

    registry.forget("take-a-hike")

    assert registry.latest("take-a-hike") is run


def test_a_run_is_manual_unless_the_batch_queue_created_it() -> None:
    """ADR-0048: a batch run is an ordinary run with origin ``batch``."""
    registry = _registry()

    assert _create(registry, "take-a-hike").origin == "manual"
    batch = registry.create("sunset", draft_brief=True, origin="batch")
    assert isinstance(batch, AiRun)
    assert batch.origin == "batch"


def test_every_subscriber_hears_each_run_finish_once() -> None:
    """The batch queue's wake-up and its row update: a run that
    finishes -- batch or manual -- is handed to every subscriber, after its
    terminal event, and a second ``finish`` is not heard again."""
    registry = _registry()
    heard: list[tuple[str, str]] = []
    registry.subscribe(lambda run: heard.append((run.id, run.phase)))
    manual = _create(registry, "take-a-hike")
    batch = registry.create("sunset", draft_brief=True, origin="batch")
    assert isinstance(batch, AiRun)

    batch.finish("failed", "no provider")
    batch.finish("done")
    manual.finish("cancelled")

    assert heard == [(batch.id, "failed"), (manual.id, "cancelled")]


def test_a_subscriber_is_called_outside_the_run_s_lock() -> None:
    """Another thread can read the run while a subscriber is still being
    called, so a subscriber that takes the batch store's lock cannot
    deadlock against a request that holds it and reads the run."""
    registry = _registry()
    seen: list[list[str]] = []

    def read_from_another_thread(run: AiRun) -> None:
        reader = threading.Thread(target=lambda: seen.append([s.state for s in run.steps]))
        reader.start()
        reader.join(timeout=5)

    registry.subscribe(read_from_another_thread)
    run = _create(registry)
    run.step("brief", "done")

    run.finish("done")

    assert seen == [["done", "pending", "pending"]]


# ----------------------------------------------------------------- deploys


def test_a_deploy_hold_refuses_new_runs_and_names_the_running_ones() -> None:
    """ADR-0050: one step, so no run can start between the answer and the hold.
    Listing names compare case-insensitively, as everywhere here."""
    registry = _registry()
    running = _create(registry, "take-a-hike")
    _create(registry, "cedar-trail")

    held = registry.hold_for_deploy(["Take-A-Hike"])

    assert held == [running]
    assert registry.deploying("take-a-hike")
    assert not registry.deploying("cedar-trail")
    running.finish("cancelled")
    assert isinstance(registry.create("take-a-hike", draft_brief=False), Deploying)


def test_two_holds_on_one_listing_need_two_releases() -> None:
    registry = _registry()
    registry.hold_for_deploy(["take-a-hike"])
    registry.hold_for_deploy(["take-a-hike"])

    registry.release_deploy(["take-a-hike"])
    assert registry.deploying("take-a-hike")

    registry.release_deploy(["take-a-hike"])
    assert not registry.deploying("take-a-hike")
    assert isinstance(registry.create("take-a-hike", draft_brief=False), AiRun)


def test_a_run_settles_once_its_listeners_have_heard() -> None:
    registry = _registry()
    heard: list[bool] = []
    registry.subscribe(lambda run: heard.append(run.wait_settled(timeout=0)))
    run = _create(registry)

    assert not run.wait_settled(timeout=0)
    run.finish("done")

    assert heard == [False]
    assert run.wait_settled(timeout=0)
