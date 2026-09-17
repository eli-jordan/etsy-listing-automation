"""``ui/runs/executor.py`` (A33, decision 7): the FIFO worker thread actually
driving ``engine.run`` through the registry, against the fixture workspace and
in-memory fakes -- no FastAPI, no TestClient (``tests/contract/test_runs_api.py``
covers the HTTP surface; this is the thread underneath it).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from etsy_listings.clients.printify.fakes import FakeCatalogClient
from etsy_listings.engine.context import EventSink, RunContext
from etsy_listings.ui.runs.events import TERMINAL_PHASES
from etsy_listings.ui.runs.executor import INTERNAL_ERROR_MESSAGE, RunExecutor
from etsy_listings.ui.runs.registry import Conflict, Run, RunRegistry
from etsy_listings.workspace.workspace import Workspace

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import copy_listing


def _context_factory(workspace: Workspace, on_event: EventSink | None) -> RunContext:
    """Printify/Etsy left ``None`` -- the fixture workspace has no shop
    configured, so those three stages report themselves blocked, and only
    `render` actually does anything. That is enough to exercise every event
    kind an unconfigured workspace's run produces; the deeper "everything
    actually applies" path already has fake-client coverage in
    `test_lifecycle.py` and friends, and this module does not re-plan
    anything -- it only turns `engine.run`'s callbacks into events.
    """
    kwargs = {"on_event": on_event} if on_event is not None else {}
    return RunContext(
        workspace=workspace,
        catalog=FakeCatalogClient([], {}, {}),
        printify=None,
        etsy=None,
        **kwargs,
    )


def _wait_until(run: Run, *, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if run.phase in TERMINAL_PHASES:
            return
        time.sleep(0.02)
    pytest.fail(f"run {run.id} never reached a terminal phase (stuck at {run.phase!r})")


@pytest.fixture
def executor(workspace_root: Path) -> RunExecutor:
    workspace = Workspace.discover(root_override=workspace_root)
    registry = RunRegistry()
    ex = RunExecutor(workspace=workspace, context_factory=_context_factory, registry=registry)
    ex.start()
    yield ex
    ex.stop()


def _create(executor: RunExecutor, kind: str, listings: list[str]) -> Run:
    result = executor.registry.create(kind, listings)  # type: ignore[arg-type]
    assert isinstance(result, Run)
    return result


# ------------------------------------------------------------------- plan runs


def test_a_plan_run_reaches_ready_and_streams_the_full_sequence(executor: RunExecutor) -> None:
    run = _create(executor, "plan", [LISTING])

    _wait_until(run)

    assert run.phase == "ready"
    phases = [e.phase for e in run.events if e.type == "phase"]
    assert phases == ["queued", "planning", "planned", "previewing", "ready"]

    kinds = [e.type for e in run.events]
    assert "stage_checking" in kinds
    assert "stage_planned" in kinds
    assert "listing_planned" in kinds
    assert "preview_rendered" in kinds, "every scene in the fixture starts unrendered"

    stage_checking = [e for e in run.events if e.type == "stage_checking"]
    assert [e.stage for e in stage_checking] == [
        "render",
        "printify_product",
        "publish",
        "etsy_listing",
        "etsy_media",
    ]

    listing_planned = next(e for e in run.events if e.type == "listing_planned")
    assert listing_planned.listing == LISTING
    assert listing_planned.fingerprint

    preview_events = [e for e in run.events if e.type == "preview_rendered"]
    assert len(preview_events) == 4, "one per colour in the fixture listing's media"


def test_a_plan_run_skips_previewing_once_everything_is_cached(executor: RunExecutor) -> None:
    """A second plan, once the first one already rendered every preview,
    finds nothing left needing one."""
    first = _create(executor, "plan", [LISTING])
    _wait_until(first)

    second = _create(executor, "plan", [LISTING])
    _wait_until(second)

    phases = [e.phase for e in second.events if e.type == "phase"]
    assert phases == ["queued", "planning", "planned", "ready"]


def test_a_second_run_for_the_same_listing_is_refused_while_the_first_is_active(
    executor: RunExecutor,
) -> None:
    first = executor.registry.create("plan", [LISTING])
    assert isinstance(first, Run)

    second = executor.registry.create("apply", [LISTING])

    assert isinstance(second, Conflict)
    assert second.active_run == first.id
    _wait_until(first)


def test_two_listings_run_one_after_the_other_on_the_single_worker_thread(
    workspace_root: Path, executor: RunExecutor
) -> None:
    copy_listing(workspace_root, "second")

    first = _create(executor, "plan", [LISTING])
    second = _create(executor, "plan", ["second"])

    _wait_until(first)
    _wait_until(second)

    assert first.phase == "ready"
    assert second.phase == "ready"


# ------------------------------------------------------------------ apply runs


def test_an_apply_run_reaches_applied_and_streams_the_full_sequence(
    executor: RunExecutor,
) -> None:
    run = _create(executor, "apply", [LISTING])

    _wait_until(run)

    assert run.phase == "applied"
    phases = [e.phase for e in run.events if e.type == "phase"]
    assert phases == ["queued", "applying", "applied"]

    applying = [e for e in run.events if e.type == "stage_applying"]
    assert [e.stage for e in applying] == ["render"], "the other four stages are blocked"

    applied = [e for e in run.events if e.type == "stage_applied"]
    assert [e.stage for e in applied] == ["render"]

    progress = [e for e in run.events if e.type == "progress"]
    assert progress, "the render stage emits at least one `ctx.emit` per scene"
    assert all(e.stage == "render" for e in progress)
    assert all(e.listing == LISTING for e in progress)


def test_cancel_is_refused_for_an_apply_run(executor: RunExecutor) -> None:
    run = _create(executor, "apply", [LISTING])

    result = executor.registry.cancel(run.id)

    assert result is False
    _wait_until(run)


# --------------------------------------------------------------------- cancel


def test_cancelling_a_queued_plan_run_marks_it_cancelled_and_it_never_executes(
    workspace_root: Path, executor: RunExecutor
) -> None:
    """Queue the worker thread up on a first listing, then cancel a second
    run before the worker ever reaches it."""
    copy_listing(workspace_root, "second")
    first = _create(executor, "plan", [LISTING])
    second = _create(executor, "plan", ["second"])

    cancelled = executor.registry.cancel(second.id)

    assert cancelled is True
    _wait_until(first)
    _wait_until(second)
    assert second.phase == "cancelled"
    assert not any(e.type == "stage_checking" for e in second.events), (
        "a cancelled-while-queued run must never have started planning"
    )


# ---------------------------------------------------------------------- defects


class _ExplodingCatalog(FakeCatalogClient):
    def blueprints(self) -> list[object]:  # type: ignore[override]
        raise RuntimeError("boom -- not a UserFacingError")


def test_a_defect_ends_the_run_failed_with_the_generic_message(
    workspace_root: Path,
) -> None:
    """`plan`'s catalog is never called for the fixture's unconfigured
    workspace (the product stage blocks first), so to reach a genuine defect
    this points printify at a shop id and lets the product stage's `desired()`
    reach the catalog and blow up with something that is not a
    `UserFacingError` -- exactly the shape decision 5 exists for."""
    from tests.support.builders import set_copy, set_shop_id, write_design

    set_shop_id(workspace_root, 28819281)
    set_copy(workspace_root, title="Take a Hike", description="A shirt for walking.")
    write_design(workspace_root, (4500, 5400))
    workspace = Workspace.discover(root_override=workspace_root)

    def factory(ws: Workspace, on_event: EventSink | None) -> RunContext:
        kwargs = {"on_event": on_event} if on_event is not None else {}
        return RunContext(workspace=ws, catalog=_ExplodingCatalog([], {}, {}), **kwargs)

    registry = RunRegistry()
    executor = RunExecutor(workspace=workspace, context_factory=factory, registry=registry)
    executor.start()
    try:
        run = executor.registry.create("plan", [LISTING])
        assert isinstance(run, Run)
        _wait_until(run)

        assert run.phase == "failed"
        failed = [e for e in run.events if e.type == "listing_failed"]
        assert failed
        assert failed[-1].message == INTERNAL_ERROR_MESSAGE
    finally:
        executor.stop()


# --------------------------------------------------------------------- shutdown


def test_stop_cancels_whatever_is_still_queued(workspace_root: Path) -> None:
    copy_listing(workspace_root, "second")
    workspace = Workspace.discover(root_override=workspace_root)
    registry = RunRegistry()
    executor = RunExecutor(workspace=workspace, context_factory=_context_factory, registry=registry)
    executor.start()

    first = executor.registry.create("plan", [LISTING])
    second = executor.registry.create("plan", ["second"])
    assert isinstance(first, Run)
    assert isinstance(second, Run)

    executor.stop()

    assert first.phase in TERMINAL_PHASES
    assert second.phase == "cancelled"


# ---------------------------------------------------------------- edge plans


def test_a_retract_only_plan_run_never_enters_previewing(
    workspace_root: Path, executor: RunExecutor
) -> None:
    """A ``deleted`` listing's plan walks the retract stage only (PRD
    61-67) -- there is no render state to ask for a preview, so
    ``needs_preview`` must answer false rather than raising."""
    from tests.support.builders import edit_listing

    edit_listing(workspace_root, LISTING, lifecycle="deleted")
    run = _create(executor, "plan", [LISTING])

    _wait_until(run)

    assert run.phase == "ready"
    phases = [e.phase for e in run.events if e.type == "phase"]
    assert "previewing" not in phases
    stages = [e.stage for e in run.events if e.type == "stage_checking"]
    assert stages == ["retract"]


# --------------------------------------------------------------------- stale


def test_an_apply_run_with_a_stale_expect_ends_stale(executor: RunExecutor) -> None:
    """A31's ``StalePlanError``, reaching decision 7's dedicated terminal
    phase -- and the ``listing_failed`` event it produces carries the fresh
    plan, not just the refusal message."""
    result = executor.registry.create("apply", [LISTING], expect={LISTING: "sha256:" + "0" * 64})
    assert isinstance(result, Run)

    _wait_until(result)

    assert result.phase == "stale"
    failed = [e for e in result.events if e.type == "listing_failed"]
    assert failed
    assert failed[-1].stale_plan is not None
    assert failed[-1].stale_plan.listing == LISTING
