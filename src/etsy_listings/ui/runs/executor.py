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

**No stage changes how it reports progress.** ``ctx.emit`` still accepts the
same stage-local event. The engine attaches listing and stage identity and
emits one :data:`EngineRunEvent` stream; this module is only its wire adapter.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from etsy_listings.engine.context import EventSink, RunContext
from etsy_listings.engine.events import (
    EngineListingFailed,
    EngineListingPlanned,
    EnginePreviewRendered,
    EngineProgress,
    EngineRunEvent,
    EngineStageApplied,
    EngineStageApplying,
    EngineStageChecking,
    EngineStageFailed,
    EngineStagePlanned,
)
from etsy_listings.engine.preview import needs_preview
from etsy_listings.engine.run import (
    StalePlanError,
    apply_listings,
    plan_fingerprint,
    plan_listings,
    preview_listing,
)
from etsy_listings.engine.stage import AnyStage
from etsy_listings.engine.stages import STAGES
from etsy_listings.errors import INTERNAL_ERROR_MESSAGE
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
            if run.kind == "plan":
                run.transition_plan("failed")
            else:
                run.transition_apply("failed")

    # -------------------------------------------------------------- plan runs

    def _append_engine_event(self, run: Run, event: EngineRunEvent) -> None:
        """Translate one engine-domain event into the public SSE vocabulary."""
        if isinstance(event, EngineStageChecking):
            run.append(lambda i: StageCheckingEvent(id=i, listing=event.listing, stage=event.stage))
        elif isinstance(event, EngineStagePlanned):
            run.append(
                lambda i: StagePlannedEvent(
                    id=i,
                    listing=event.listing,
                    stage_plan=stage_plan_dto(event.stage_plan),
                )
            )
        elif isinstance(event, EngineListingPlanned):
            run.append(
                lambda i: ListingPlannedEvent(
                    id=i,
                    listing=event.listing,
                    plan=plan_dto(event.plan),
                    fingerprint=plan_fingerprint(event.plan),
                )
            )
        elif isinstance(event, EngineListingFailed):
            stale_plan = (
                plan_dto(event.error.planned.plan)
                if isinstance(event.error, StalePlanError)
                else None
            )
            run.append(
                lambda i: ListingFailedEvent(
                    id=i,
                    listing=event.listing,
                    message=str(event.error),
                    stale_plan=stale_plan,
                )
            )
        elif isinstance(event, EnginePreviewRendered):
            run.append(
                lambda i: PreviewRenderedEvent(
                    id=i,
                    listing=event.listing,
                    template=event.template,
                    colour=event.colour,
                )
            )
        elif isinstance(event, EngineStageApplying):
            run.append(lambda i: StageApplyingEvent(id=i, listing=event.listing, stage=event.stage))
        elif isinstance(event, EngineProgress):
            run.append(
                lambda i: ProgressEvent(
                    id=i,
                    listing=event.listing,
                    stage=event.stage,
                    message=event.message,
                    swatches=event.swatches,
                )
            )
        elif isinstance(event, EngineStageApplied):
            run.append(lambda i: StageAppliedEvent(id=i, listing=event.listing, stage=event.stage))
        else:
            assert isinstance(event, EngineStageFailed)  # noqa: S101 - closed union
            run.append(
                lambda i: StageFailedEvent(
                    id=i,
                    listing=event.listing,
                    stage=event.stage,
                    message=event.message,
                )
            )

    def _run_plan(self, run: Run) -> None:
        run.transition_plan("planning")
        ctx = self.context_factory(self.workspace, None)

        def emit(event: EngineRunEvent) -> None:
            self._append_engine_event(run, event)

        def stop() -> bool:
            return self._should_stop(run)

        report = plan_listings(ctx, run.listings, self.stages, on_event=emit, should_stop=stop)

        if self._should_stop(run):
            run.transition_plan("cancelled")
            return
        run.transition_plan("planned")

        needing_preview = tuple(
            outcome.planned
            for outcome in report.outcomes
            if outcome.planned is not None and needs_preview(outcome.planned)
        )
        if needing_preview:
            run.transition_plan("previewing")

            for result in needing_preview:
                if self._should_stop(run):
                    break
                preview_listing(ctx, result, emit, should_stop=stop)

        if self._should_stop(run):
            run.transition_plan("cancelled")
            return
        run.transition_plan("ready")

    # ------------------------------------------------------------- apply runs

    def _run_apply(self, run: Run) -> None:
        run.transition_apply("applying")

        def emit(event: EngineRunEvent) -> None:
            self._append_engine_event(run, event)

        ctx = self.context_factory(self.workspace, None)
        report = apply_listings(
            ctx,
            run.listings,
            self.stages,
            on_event=emit,
            expect=run.expect,
            should_stop=lambda: self._should_stop(run),
        )

        errors = [outcome.error for outcome in report.failures]
        if not errors:
            run.transition_apply("applied")
        elif all(isinstance(error, StalePlanError) for error in errors):
            run.transition_apply("stale")
        else:
            run.transition_apply("failed")
