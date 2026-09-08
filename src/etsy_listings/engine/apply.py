"""Executes a :class:`PlannedRun`, strictly sequentially (A3: apply never
parallelises writes -- only ``plan``'s read-only live fetches may fan out)."""

from __future__ import annotations

from datetime import UTC, datetime

from etsy_listings import __about__
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import PlannedRun


def execute(ctx: RunContext, planned: PlannedRun, lock: Lockfile) -> Lockfile:
    """Run every stage the plan flagged, in pipeline order, folding each result
    into a new lockfile. Resumable: a stage that already appears in
    ``stages_completed`` with no pending change is a no-op re-check, not a
    duplicate action -- this is what lets a failed ``apply`` be re-run safely.

    Nothing here re-resolves anything. Each stage is handed back the desired
    document and the live state ``build_plan`` already got from it, so the
    document that was hashed is the document that gets sent, by construction
    rather than by two call paths agreeing.

    Nor does anything here know the lockfile's shape. Each result is folded in
    by :meth:`Lockfile.fold`, which owns the replace-versus-merge rules for
    all four axes -- this loop only decides *which* stages run and in what
    order, which is the part that is genuinely ``apply``'s business (A3).
    """
    result_lock = lock

    for state in planned.states:
        stage_plan = state.stage_plan
        if not stage_plan.will_run and not stage_plan.changes:
            continue
        stage = state.stage
        ctx.emit(f"applying {stage.name}")
        # `lock`, not `result_lock`: a stage reads the *previous* lockfile,
        # the one describing the world before this run started. Handing it a
        # lockfile already carrying an earlier stage's results would let stage
        # order change what a stage sees.
        result = stage.apply(ctx, stage_plan, state.desired, state.live, lock)
        result_lock = result_lock.fold(stage.name, result)

    return result_lock.stamped(
        tool_version=__about__.VERSION,
        applied_at=datetime.now(UTC).isoformat(),
    )
