"""Executes a :class:`Plan`, strictly sequentially (A3: apply never parallelises
writes -- only ``plan``'s read-only live fetches may fan out)."""

from __future__ import annotations

from datetime import UTC, datetime

from etsy_listings import __about__
from etsy_listings.engine.change import Plan
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.stage import AnyStage


def execute(ctx: RunContext, plan: Plan, lock: Lockfile, stages: list[AnyStage]) -> Lockfile:
    """Run every stage the plan flagged, in pipeline order, folding each result
    into a new lockfile. Resumable: a stage that already appears in
    ``stages_completed`` with no pending change is a no-op re-check, not a
    duplicate action -- this is what lets a failed ``apply`` be re-run safely.
    """
    stages_by_name = {stage.name: stage for stage in stages}
    applied = dict(lock.applied)
    completed = list(lock.stages_completed)

    for stage_plan in plan.stage_plans:
        if not stage_plan.will_run and not stage_plan.changes:
            continue
        stage = stages_by_name[stage_plan.stage]
        desired = stage.desired(ctx, plan.listing)
        ctx.emit(f"applying {stage.name}")
        stage.apply(ctx, stage_plan, desired)
        if stage.name not in completed:
            completed.append(stage.name)

    return Lockfile(
        tool_version=__about__.VERSION,
        applied_at=datetime.now(UTC).isoformat(),
        applied=applied,
        remote=lock.remote,
        outputs=lock.outputs,
        stages_completed=completed,
    )
