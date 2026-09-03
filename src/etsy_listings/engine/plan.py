"""Builds a :class:`Plan` by walking the stage pipeline. A1/A2/A3.

Only this module (and ``apply``) may compute a diff -- the CLI renderer and the
UI's future JSON serialiser both consume the resulting :class:`Plan` /
:class:`StagePlan` / ``Change`` objects without comparing state themselves. That
is what keeps the CLI and UI enforcing identical rules.
"""

from __future__ import annotations

from etsy_listings.engine.change import Plan, StagePlan
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.stage import AnyStage


def build_plan(
    ctx: RunContext,
    listing: str,
    lock: Lockfile,
    stages: list[AnyStage],
) -> Plan:
    """Three-way compare desired/applied/live across every stage, in order.

    Live reads are the only part of a run that may fan out over a thread pool
    (A3) -- not implemented yet, since Phase 0/1 have no stage whose
    ``read_live`` does real I/O. Each stage's own ``plan()`` computes the diff;
    this function only orchestrates the walk and assembles the result.
    """
    stage_plans: list[StagePlan] = []
    for stage in stages:
        desired = stage.desired(ctx, listing)
        applied = stage.last_applied(lock)
        live = None if stage.local else stage.read_live(ctx, lock)
        stage_plans.append(stage.plan(desired, applied, live))

    etsy_listing_id = lock.remote.get("etsy_listing_id")
    is_live = lock.remote.get("etsy_listing_state") not in (None, "draft")

    return Plan(
        listing=listing,
        is_live=is_live,
        etsy_listing_id=etsy_listing_id,
        stage_plans=tuple(stage_plans),
    )
