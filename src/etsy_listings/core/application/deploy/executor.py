from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from functools import singledispatch

from etsy_listings.core.application.ai.coordinator import AiCoordinator
from etsy_listings.core.application.dependencies import ContextFactory
from etsy_listings.core.application.deploy.events import (
    TERMINAL_PHASES,
    AnyRunEvent,
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
from etsy_listings.core.application.deploy.registry import Run, RunRegistry, abandon
from etsy_listings.core.application.job_gate import JobGate
from etsy_listings.core.engine.context import RunContext
from etsy_listings.core.engine.events import (
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
    RunHooks,
)
from etsy_listings.core.engine.plan import PlannedRun
from etsy_listings.core.engine.preview import needs_preview
from etsy_listings.core.engine.run import (
    StalePlanError,
    apply_listings,
    plan_fingerprint,
    plan_listings,
    preview_listing,
)
from etsy_listings.core.engine.stage import AnyStage
from etsy_listings.core.engine.stages import STAGES, publishing_pipeline
from etsy_listings.core.errors import INTERNAL_ERROR_MESSAGE
from etsy_listings.core.workspace.workspace import Workspace

logger = logging.getLogger(__name__)


@dataclass
class RunExecutor:
    workspace: Workspace
    context_factory: ContextFactory
    registry: RunRegistry
    stages: list[AnyStage] = field(default_factory=lambda: list(STAGES))
    ai: AiCoordinator | None = None
    """Whose AI work a run takes its listings from before reading them
    (ADR-0050); a host with no AI work passes none."""
    gate: JobGate = field(default_factory=JobGate)
    """The backup's pause (workspace-backup spec, *Pausing jobs*); a host
    that never backs up keeps one that is never paused."""
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="etsy-listings-runs", daemon=False)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.registry.drain_and_cancel()
        self.registry.wake()
        if self._thread is not None:
            self._thread.join()

    def _loop(self) -> None:
        while True:
            run_id = self.registry.dequeue(timeout=0.5)
            if run_id is not None:
                self._admitted(run_id)
            if self._stop.is_set():
                return

    def _admitted(self, run_id: str) -> None:
        run = self.registry.get(run_id)
        if run is None or run.phase in TERMINAL_PHASES:
            return
        ticket = self.gate.wait_admit(_backup_wait_label(run))
        if ticket is None:
            abandon(run)
            return
        with ticket:
            # A plan cancelled while it was held has already ended.
            if run.phase not in TERMINAL_PHASES:
                self._execute(run)

    def _should_stop(self, run: Run) -> bool:
        return run.cancel_requested or self._stop.is_set()

    def _pipeline(self, run: Run) -> list[AnyStage]:
        return publishing_pipeline(self.stages, publish=run.publish)

    def _yield_to_deploy(self, listings: Sequence[str]) -> AbstractContextManager[None]:
        return nullcontext() if self.ai is None else self.ai.yield_to_deploy(listings)

    def _execute(self, run: Run) -> None:
        try:
            with self._yield_to_deploy(run.listings):
                if run.kind == "plan":
                    self._run_plan(run)
                else:
                    self._run_apply(run)
        except Exception:
            # A defect gets a traceback in the log and a generic
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

    def _append_engine_event(self, run: Run, event: EngineRunEvent) -> None:
        run.append(_public_event(event))

    def _run_plan(self, run: Run) -> None:
        run.transition_plan("planning")
        ctx = self.context_factory(self.workspace.snapshot(), None)

        def emit(event: EngineRunEvent) -> None:
            self._append_engine_event(run, event)

        def stop() -> bool:
            return self._should_stop(run)

        report = plan_listings(
            ctx, run.listings, self._pipeline(run), hooks=RunHooks(on_event=emit, should_stop=stop)
        )

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
            self._preview(run, ctx, needing_preview, RunHooks(on_event=emit, should_stop=stop))

        if self._should_stop(run):
            run.transition_plan("cancelled")
            return
        run.transition_plan("ready")

    def _preview(
        self, run: Run, ctx: RunContext, needing_preview: tuple[PlannedRun, ...], hooks: RunHooks
    ) -> None:
        previewed: list[str] = []
        for result in needing_preview:
            if self._should_stop(run):
                break
            preview_listing(ctx, result, hooks.on_event, should_stop=hooks.should_stop)
            previewed.append(result.plan.listing)

        # Plan again over the previews (architecture, *The calibrator*).
        if previewed and not self._should_stop(run):
            plan_listings(ctx, previewed, self._pipeline(run), hooks=hooks)

    def _run_apply(self, run: Run) -> None:
        run.transition_apply("applying")

        def emit(event: EngineRunEvent) -> None:
            self._append_engine_event(run, event)

        ctx = self.context_factory(self.workspace.snapshot(), None)
        report = apply_listings(
            ctx,
            run.listings,
            self._pipeline(run),
            expect=run.expect,
            hooks=RunHooks(on_event=emit, should_stop=lambda: self._should_stop(run)),
        )

        errors = [outcome.error for outcome in report.failures]
        if not errors:
            run.transition_apply("applied")
        elif all(isinstance(error, StalePlanError) for error in errors):
            run.transition_apply("stale")
        else:
            run.transition_apply("failed")


_EventFactory = Callable[[int], AnyRunEvent]
"""What :meth:`Run.append` takes: the public event, given the id it assigns."""


@singledispatch
def _public_event(event: EngineRunEvent) -> _EventFactory:
    raise TypeError(f"no public event for {type(event).__name__}")


@_public_event.register(EngineStageFailed)
def _stage_failed(event: EngineStageFailed) -> _EventFactory:
    return lambda i: StageFailedEvent(
        id=i,
        listing=event.listing,
        stage=event.stage,
        message=event.message,
    )


@_public_event.register(EngineStageChecking)
def _stage_checking(event: EngineStageChecking) -> _EventFactory:
    return lambda i: StageCheckingEvent(id=i, listing=event.listing, stage=event.stage)


@_public_event.register(EngineStagePlanned)
def _stage_planned(event: EngineStagePlanned) -> _EventFactory:
    return lambda i: StagePlannedEvent(
        id=i,
        listing=event.listing,
        stage_plan=stage_plan_dto(event.stage_plan),
    )


@_public_event.register(EngineListingPlanned)
def _listing_planned(event: EngineListingPlanned) -> _EventFactory:
    return lambda i: ListingPlannedEvent(
        id=i,
        listing=event.listing,
        plan=plan_dto(event.plan),
        fingerprint=plan_fingerprint(event.plan),
    )


@_public_event.register(EngineListingFailed)
def _listing_failed(event: EngineListingFailed) -> _EventFactory:
    stale_plan = (
        plan_dto(event.error.planned.plan) if isinstance(event.error, StalePlanError) else None
    )
    return lambda i: ListingFailedEvent(
        id=i,
        listing=event.listing,
        message=str(event.error),
        stale_plan=stale_plan,
    )


@_public_event.register(EnginePreviewRendered)
def _preview_rendered(event: EnginePreviewRendered) -> _EventFactory:
    return lambda i: PreviewRenderedEvent(
        id=i,
        listing=event.listing,
        template=event.template,
        colour=event.colour,
    )


@_public_event.register(EngineStageApplying)
def _stage_applying(event: EngineStageApplying) -> _EventFactory:
    return lambda i: StageApplyingEvent(id=i, listing=event.listing, stage=event.stage)


@_public_event.register(EngineProgress)
def _progress(event: EngineProgress) -> _EventFactory:
    return lambda i: ProgressEvent(
        id=i,
        listing=event.listing,
        stage=event.stage,
        message=event.message,
        swatches=event.swatches,
    )


@_public_event.register(EngineStageApplied)
def _stage_applied(event: EngineStageApplied) -> _EventFactory:
    return lambda i: StageAppliedEvent(id=i, listing=event.listing, stage=event.stage)


def _backup_wait_label(run: Run) -> str:
    if run.scope == "workspace":
        return f"Workspace {run.kind}"
    if run.scope == "batch":
        return f"Batch {run.kind} for {', '.join(run.listings)}"
    return f"Deploy {run.kind} for {', '.join(run.listings)}"
