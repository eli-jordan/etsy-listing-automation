"""The FIFO worker thread that actually runs a plan or an apply (A33,
decision 7).

**One thread for the whole workspace, not one lock per listing.** The
registry's per-listing locks decide whether a *new* run may be queued at all;
they do not, by themselves, stop two runs from executing at once -- that
guarantee comes from there being exactly one thread here to execute either of
them. This is what keeps A3's "apply never parallelises writes" true one level
up: raising the worker count later would be the whole of parallelising,
because the lock model already exists.

**Contexts are injected, never assembled here (`connections.py`'s own
rule).** :data:`ContextFactory` is `connections.run_context`'s shape --
``(workspace, on_event)`` -- so this module never decides which credential to
resolve or when; it only decides *when to call the factory* and *what to do
with the ``RunContext`` it hands back*.

**No stage changes how it reports progress.** ``ctx.emit``'s existing
``Event`` reaches :func:`RunExecutor._run_apply`'s ``on_event`` unchanged; what
turns it into a :class:`~etsy_listings.ui.runs.events.ProgressEvent` naming a
stage is this module remembering which stage
:attr:`~etsy_listings.engine.run.RunObserver.on_stage_applying` last named for
this listing -- a piece of state no stage needs to know exists.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from etsy_listings.engine.change import Plan, StagePlan
from etsy_listings.engine.context import Event, EventSink, RunContext
from etsy_listings.engine.plan import PlannedRun
from etsy_listings.engine.run import (
    RunObserver,
    StalePlanError,
    apply_listings,
    plan_fingerprint,
    plan_listings,
    preview_listing,
)
from etsy_listings.engine.stage import AnyStage, Blocked
from etsy_listings.engine.stages import STAGES
from etsy_listings.engine.stages.render import RenderSnapshot, RenderStage
from etsy_listings.errors import INTERNAL_ERROR_MESSAGE, UserFacingError
from etsy_listings.ui.runs.events import (
    TERMINAL_PHASES,
    ListingFailedEvent,
    ListingPlannedEvent,
    PreviewRenderedEvent,
    ProgressEvent,
    StageAppliedEvent,
    StageApplyingEvent,
    StageCheckingEvent,
    StageFailedEvent,
    StagePlannedEvent,
    plan_dto,
    stage_plan_dto,
)
from etsy_listings.ui.runs.registry import Run, RunRegistry
from etsy_listings.workspace.workspace import Workspace

logger = logging.getLogger(__name__)

ContextFactory = Callable[[Workspace, EventSink | None], RunContext]
"""How the executor builds a run's :class:`~etsy_listings.engine.context.RunContext`
(decision 7's "contexts are injected"). ``connections.run_context`` is the
default every real server uses; a test wires one to in-memory fakes instead,
by swapping this one callable -- nothing else here knows how a client is
assembled."""


def _needs_preview(planned: PlannedRun) -> bool:
    """Whether this listing's plan has a scene worth spending a preview
    render on -- ``RenderStage.snapshot``'s own ``stale``/``missing`` states,
    minus whatever already has one (A32's ``preview`` field)."""
    render_state = next((s for s in planned.states if s.stage.name == RenderStage.name), None)
    if render_state is None or isinstance(render_state.desired, Blocked):
        return False
    snapshot = render_state.stage_plan.snapshot
    if not isinstance(snapshot, RenderSnapshot):
        return False
    return any(
        scene.state in ("stale", "missing") and not scene.preview for scene in snapshot.scenes
    )


@dataclass
class RunExecutor:
    """Owns the worker thread. One instance per running server
    (``ui/api/app.py``'s lifespan starts and joins it)."""

    workspace: Workspace
    context_factory: ContextFactory
    registry: RunRegistry
    stages: list[AnyStage] = field(default_factory=lambda: list(STAGES))
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="etsy-listings-runs", daemon=False)
        self._thread.start()

    def stop(self) -> None:
        """Shutdown (decision 7): cancel whatever is still queued, then wait
        for whatever the worker thread is doing right now -- a plan run's next
        boundary, or an apply run's current stage -- to finish and start
        nothing else. Not a daemon thread, so a caller that forgets to call
        this hangs the process on exit rather than silently dropping work.
        """
        self._stop.set()
        self.registry.drain_and_cancel()
        if self._thread is not None:
            self._thread.join()

    # -------------------------------------------------------------- the loop

    def _loop(self) -> None:
        while True:
            run_id = self.registry.dequeue(timeout=0.5)
            if run_id is None:
                if self._stop.is_set():
                    return
                continue
            run = self.registry.get(run_id)
            if run is not None and run.phase not in TERMINAL_PHASES:
                self._execute(run)
            if self._stop.is_set():
                return

    def _should_stop(self, run: Run) -> bool:
        """A plan run stops for its own cancel *or* a shutdown; an apply run
        never honours ``cancel_requested`` (decision 8 -- the registry never
        sets it for one), only a shutdown."""
        if run.kind == "apply":
            return self._stop.is_set()
        return run.cancel_requested or self._stop.is_set()

    def _execute(self, run: Run) -> None:
        try:
            if run.kind == "plan":
                self._run_plan(run)
            else:
                self._run_apply(run)
        except Exception:
            # Decision 5: a defect gets a traceback in the log and a generic
            # message on the page -- never the exception text itself, which
            # might be anything from a stack of internal paths to a client
            # library's own error string.
            logger.exception("run %s (%s) ended with an unhandled error", run.id, run.kind)
            listing = run.listings[0] if run.listings else ""
            run.append(
                lambda i: ListingFailedEvent(id=i, listing=listing, message=INTERNAL_ERROR_MESSAGE)
            )
            run.transition("failed")

    # -------------------------------------------------------------- plan runs

    def _plan_observer(
        self, run: Run, *, capture: dict[str, PlannedRun] | None = None
    ) -> RunObserver:
        def on_stage_checking(listing: str, stage: str) -> None:
            run.append(lambda i: StageCheckingEvent(id=i, listing=listing, stage=stage))

        def on_stage_planned(listing: str, stage_plan: StagePlan) -> None:
            run.append(
                lambda i: StagePlannedEvent(
                    id=i, listing=listing, stage_plan=stage_plan_dto(stage_plan)
                )
            )

        def on_listing_planned(listing: str, result: PlannedRun) -> None:
            if capture is not None:
                capture[listing] = result
            fingerprint = plan_fingerprint(result.plan)
            plan: Plan = result.plan
            run.append(
                lambda i: ListingPlannedEvent(
                    id=i, listing=listing, plan=plan_dto(plan), fingerprint=fingerprint
                )
            )

        def on_failure(listing: str, error: UserFacingError) -> None:
            stale_plan = plan_dto(error.planned.plan) if isinstance(error, StalePlanError) else None
            run.append(
                lambda i: ListingFailedEvent(
                    id=i, listing=listing, message=str(error), stale_plan=stale_plan
                )
            )

        return RunObserver(
            on_stage_checking=on_stage_checking,
            on_stage_planned=on_stage_planned,
            on_listing_planned=on_listing_planned,
            on_failure=on_failure,
        )

    def _run_plan(self, run: Run) -> None:
        run.transition("planning")
        ctx = self.context_factory(self.workspace, None)
        planned: dict[str, PlannedRun] = {}
        observer = self._plan_observer(run, capture=planned)

        def stop() -> bool:
            return self._should_stop(run)

        plan_listings(ctx, run.listings, self.stages, observer=observer, should_stop=stop)

        if self._should_stop(run):
            run.transition("cancelled")
            return
        run.transition("planned")

        needing_preview = {
            listing: result for listing, result in planned.items() if _needs_preview(result)
        }
        if needing_preview:
            run.transition("previewing")

            def on_preview_rendered(listing: str, template: str, colour: str | None) -> None:
                run.append(
                    lambda i: PreviewRenderedEvent(
                        id=i, listing=listing, template=template, colour=colour
                    )
                )

            preview_observer = RunObserver(on_preview_rendered=on_preview_rendered)
            for result in needing_preview.values():
                if self._should_stop(run):
                    break
                preview_listing(ctx, result, preview_observer, should_stop=stop)

        if self._should_stop(run):
            run.transition("cancelled")
            return
        run.transition("ready")

    # ------------------------------------------------------------- apply runs

    def _run_apply(self, run: Run) -> None:
        run.transition("applying")
        current: dict[str, str | None] = {"listing": None, "stage": None}

        def on_event(event: Event) -> None:
            listing = current["listing"] or ""
            stage = current["stage"]
            swatches = tuple(event.swatches)
            run.append(
                lambda i: ProgressEvent(
                    id=i, listing=listing, stage=stage, message=event.message, swatches=swatches
                )
            )

        def on_stage_applying(listing: str, stage: str) -> None:
            current["listing"] = listing
            current["stage"] = stage
            run.append(lambda i: StageApplyingEvent(id=i, listing=listing, stage=stage))

        def on_stage_applied(listing: str, stage: str) -> None:
            run.append(lambda i: StageAppliedEvent(id=i, listing=listing, stage=stage))
            current["stage"] = None

        def on_stage_failed(listing: str, stage: str, message: str) -> None:
            run.append(
                lambda i: StageFailedEvent(id=i, listing=listing, stage=stage, message=message)
            )

        base = self._plan_observer(run)
        observer = RunObserver(
            on_stage_checking=base.on_stage_checking,
            on_stage_planned=base.on_stage_planned,
            on_listing_planned=base.on_listing_planned,
            on_failure=base.on_failure,
            on_stage_applying=on_stage_applying,
            on_stage_applied=on_stage_applied,
            on_stage_failed=on_stage_failed,
        )

        ctx = self.context_factory(self.workspace, on_event)
        report = apply_listings(
            ctx,
            run.listings,
            self.stages,
            observer=observer,
            expect=run.expect,
            should_stop=lambda: self._should_stop(run),
        )

        errors = [outcome.error for outcome in report.failures]
        if not errors:
            run.transition("applied")
        elif all(isinstance(error, StalePlanError) for error in errors):
            run.transition("stale")
        else:
            run.transition("failed")
