"""Executes a :class:`PlannedRun`, strictly sequentially (A3: apply never
parallelises writes -- only ``plan``'s read-only live fetches may fan out)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from etsy_listings import __about__
from etsy_listings.engine.context import Event, RunContext
from etsy_listings.engine.events import (
    EngineEventSink,
    EngineProgress,
    EngineStageApplied,
    EngineStageApplying,
    EngineStageFailed,
    ignore_engine_event,
)
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import PlannedRun
from etsy_listings.errors import INTERNAL_ERROR_MESSAGE, UserFacingError

RecordSink = Callable[[Lockfile], None]
"""Called with the stamped, folded lockfile after every stage `execute`
completes -- and once more, marked incomplete, when a stage raises. A29: this
is what makes a partial apply durable through a crash, not just through a
clean return. `apply_listings` is the caller that supplies one that writes
`state.lock.json`; a caller with no interest in recording gets the no-op
default, which is every direct `execute` call that existed before A29."""


def _ignore_record(lock: Lockfile) -> None:
    return None


def _stamp(lock: Lockfile) -> Lockfile:
    return lock.stamped(tool_version=__about__.VERSION, applied_at=datetime.now(UTC).isoformat())


def _never_stop() -> bool:
    return False


def execute(
    ctx: RunContext,
    planned: PlannedRun,
    lock: Lockfile,
    *,
    on_event: EngineEventSink = ignore_engine_event,
    record: RecordSink = _ignore_record,
    should_stop: Callable[[], bool] = _never_stop,
) -> Lockfile:
    """Run every stage the plan flagged, in pipeline order, folding each result
    into a new lockfile. Resumable: a stage that already appears in
    ``stages_completed`` with no pending change is a no-op re-check, not a
    duplicate action -- this is what lets a failed ``apply`` be re-run safely.

    Nothing here re-resolves anything, and nothing here re-*reads* anything.
    Each stage is handed back the three states ``build_plan`` already
    resolved -- its desired document, its decoded ``applied`` subtree and its
    live state -- so the document that was hashed is the document that gets
    sent, by construction rather than by two call paths agreeing.

    Nor does anything here know the lockfile's shape. Each result is folded in
    by :meth:`Lockfile.fold`, which owns the replace-versus-merge rules for
    all four axes -- this loop only decides *which* stages run and in what
    order, which is the part that is genuinely ``apply``'s business (A3).

    **``remote`` is threaded live through the run; ``applied`` is not (A26).**
    A stage's own ``lock.applied`` stays exactly what it was before this run
    started, so stage order still cannot change what a stage sees there. But
    an id an earlier stage minted *this run* -- ``publish`` creating the Etsy
    listing ``etsy_listing`` is about to patch -- has to be visible to a later
    stage's ``apply`` in the same run, or a first `apply` that creates a
    Printify product, publishes it, and then cannot find the listing id it
    just minted would need running twice.

    **A29: ``record`` is called after every stage that succeeds, and once
    more if one raises.** Before this, the lockfile ``execute`` builds only
    ever reached disk if the whole loop returned -- so a stage raising after
    ``printify_product`` created a product lost that id, and PRD 48's
    duplicate-create guard then refused the next attempt outright, forever.
    ``record`` is called with the same lockfile ``fold`` just produced,
    stamped, so a crash between two stages still leaves the earlier one
    recorded. On a raise, the lockfile folded so far is stamped, marked
    incomplete for the stage that raised, recorded, and the exception is
    re-raised unchanged -- ``execute`` still reports the failure exactly as
    it always did; only what reaches disk on the way out is new.

    ``fold`` never touches ``incomplete`` -- it is not one of the four axes a
    stage writes to -- so a marker an earlier, failed run left behind rides
    along through every successful fold of a retry until the loop finishes
    without anything raising, at which point it is explicitly cleared and
    recorded once more. That extra call only happens when there was a marker
    to clear, which is also what makes a retry that turns out to need no
    stage at all (every ``StagePlan`` already satisfied) still clear it: the
    loop never runs, but the check after it does.

    **A33: ``on_event`` brackets each stage's own ``apply``.** It emits one
    closed engine-event vocabulary, including stage progress with listing and
    stage identity attached here rather than reconstructed by a caller.

    **``should_stop`` is a graceful pause, not a failure (A33, decision 7's
    shutdown paragraph).** Checked before each stage that has not started yet
    -- never inside one, so a stage already running always finishes and
    records itself exactly as A29 already guarantees. Stopping early leaves
    ``incomplete`` exactly as it was: unlike a raise, nothing here failed, so
    no new marker is set; but the plan was not fully carried out either, so an
    existing marker from an earlier failed run is not cleared -- that only
    happens once every stage has had its turn. The next ``apply`` of this
    listing, whenever it comes, simply finds the stages ``should_stop`` skipped
    still pending, the same way it would after any other pause. Defaults to a
    callable that never stops, so this is invisible to every caller that
    predates it.
    """
    listing = planned.plan.listing
    result_lock = lock
    remote = dict(lock.remote)
    stopped = False

    for state in planned.states:
        if should_stop():
            stopped = True
            break
        stage_plan = state.stage_plan
        if not stage_plan.will_run:
            continue
        stage = state.stage
        on_event(EngineStageApplying(listing, stage.name))
        stage_name = stage.name

        def forward_progress(event: Event, stage_name: str = stage_name) -> None:
            on_event(EngineProgress(listing, stage_name, event.message, event.swatches))

        stage_ctx = ctx.with_event_sink(forward_progress)
        stage_ctx.emit(f"applying {stage.name}")
        # `lock.applied`, not `result_lock.applied`: a stage's own applied
        # document is still the one describing the world before this run
        # started. `remote` is the accumulator instead, so an id minted a
        # moment ago in this same loop is there to be read.
        live_lock = lock.model_copy(update={"remote": remote})
        try:
            result = stage.apply(stage_ctx, state.desired, state.applied, state.live, live_lock)
        except Exception as exc:
            record(_stamp(result_lock.marked_incomplete(stage.name)))
            # A `UserFacingError`'s message is safe to show verbatim (the
            # same rule `_over` already applies to a listing-level failure);
            # anything else is a defect and may carry whatever its own text
            # happens to say, so it is masked here, at the one place that
            # decides, rather than trusting every future event consumer to guess.
            reported = str(exc) if isinstance(exc, UserFacingError) else INTERNAL_ERROR_MESSAGE
            on_event(EngineStageFailed(listing, stage.name, reported))
            raise
        result_lock = result_lock.fold(stage.name, result)
        remote = {**remote, **result.remote}
        record(_stamp(result_lock))
        on_event(EngineStageApplied(listing, stage.name))

    if not stopped and result_lock.incomplete is not None:
        result_lock = result_lock.completed()
        record(_stamp(result_lock))

    return _stamp(result_lock)
