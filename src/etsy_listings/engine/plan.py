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

    Every stage's ``read_live`` is called, ``local`` ones included: a local
    stage has no *remote* state, but it can still have outputs on disk that
    were deleted or edited since the last apply, and a plan that doesn't look
    is a plan that reports "no changes" over a half-empty render cache. What
    ``local`` buys is that the read is cheap and local, so it stays out of
    A3's live-fetch thread pool (not implemented yet -- no stage in Phase 0/1
    does remote I/O), and that a difference is reported as work to redo rather
    than as drift. Each stage's own ``plan()`` computes the diff; this
    function only orchestrates the walk and assembles the result.
    """
    stage_plans: list[StagePlan] = []
    for stage in stages:
        desired = stage.desired(ctx, listing)
        applied = stage.last_applied(lock)
        live = stage.read_live(ctx, listing, lock)
        stage_plans.append(stage.plan(desired, applied, live))

    etsy_listing_id = lock.remote.get("etsy_listing_id")
    is_live = lock.remote.get("etsy_listing_state") not in (None, "draft")

    return Plan(
        listing=listing,
        is_live=is_live,
        etsy_listing_id=etsy_listing_id,
        stage_plans=tuple(stage_plans),
    )
