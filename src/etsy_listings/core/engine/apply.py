from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from etsy_listings import __about__
from etsy_listings.core.engine.context import Event, RunContext
from etsy_listings.core.engine.events import (
    EngineEventSink,
    EngineProgress,
    EngineStageApplied,
    EngineStageApplying,
    EngineStageFailed,
    RunHooks,
)
from etsy_listings.core.engine.lock import Lockfile
from etsy_listings.core.engine.plan import PlannedRun, StageState
from etsy_listings.core.engine.stage import StageApplyResult
from etsy_listings.core.errors import INTERNAL_ERROR_MESSAGE, UserFacingError

RecordSink = Callable[[Lockfile], None]
"""Called with the stamped, folded lockfile after every stage `execute`
completes -- and once more, marked incomplete, when a stage raises. ADR-0037: this
is what makes a partial apply durable through a crash, not just through a
clean return. `apply_listings` is the caller that supplies one that writes
`state.lock.json`; a caller with no interest in recording gets the no-op
default."""


def _ignore_record(_lock: Lockfile) -> None:
    return None


def _stamp(lock: Lockfile) -> Lockfile:
    return lock.stamped(tool_version=__about__.VERSION, applied_at=datetime.now(UTC).isoformat())


@dataclass(frozen=True)
class _StageRun:
    ctx: RunContext
    listing: str
    lock: Lockfile
    on_event: EngineEventSink
    record: RecordSink

    def apply(
        self, state: StageState, remote: dict[str, Any], result_lock: Lockfile
    ) -> StageApplyResult:
        listing, stage = self.listing, state.stage
        self.on_event(EngineStageApplying(listing, stage.name))
        stage_name = stage.name

        def forward_progress(event: Event, stage_name: str = stage_name) -> None:
            self.on_event(EngineProgress(listing, stage_name, event.message, event.swatches))

        stage_ctx = self.ctx.with_event_sink(forward_progress)
        stage_ctx.emit(f"applying {stage.name}")
        live_lock = self.lock.model_copy(update={"remote": remote})
        try:
            return stage.apply(stage_ctx, state.desired, state.applied, state.live, live_lock)
        except Exception as exc:
            self.record(_stamp(result_lock.marked_incomplete(stage.name)))
            # Only a `UserFacingError`'s message is safe to show; a defect's
            # text may carry anything, so it is masked here, where it is decided.
            reported = str(exc) if isinstance(exc, UserFacingError) else INTERNAL_ERROR_MESSAGE
            self.on_event(EngineStageFailed(listing, stage.name, reported))
            raise


def execute(
    ctx: RunContext,
    planned: PlannedRun,
    lock: Lockfile,
    *,
    hooks: RunHooks = RunHooks(),
    record: RecordSink = _ignore_record,
) -> Lockfile:
    on_event, should_stop = hooks.on_event, hooks.should_stop
    listing = planned.plan.listing
    run = _StageRun(ctx, listing, lock, on_event, record)
    result_lock = lock
    remote = dict(lock.remote)
    stopped = False

    for state in planned.states:
        if not state.stage_plan.will_run:
            continue
        if should_stop():
            stopped = True
            break
        result = run.apply(state, remote, result_lock)
        result_lock = result_lock.fold(state.stage.name, result)
        remote = {**remote, **result.remote}
        record(_stamp(result_lock))
        on_event(EngineStageApplied(listing, state.stage.name))

    if not stopped and result_lock.incomplete is not None:
        result_lock = result_lock.completed()
        record(_stamp(result_lock))

    return _stamp(result_lock)
