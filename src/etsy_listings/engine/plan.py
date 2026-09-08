"""Builds a :class:`Plan` by walking the stage pipeline. A1/A2/A3.

Only this module (and ``apply``) may compute a diff -- the CLI renderer and the
UI's future JSON serialiser both consume the resulting :class:`Plan` /
:class:`StagePlan` / ``Change`` objects without comparing state themselves. That
is what keeps the CLI and UI enforcing identical rules.

Planning **keeps** what it resolved. It used to hand back the ``Plan`` alone
and drop the desired and live states it had just built, so ``execute`` asked
every stage for them a second time: one ``apply`` parsed the listing and its
profile five times over, hashed every design four times, resolved the variant
matrix twice and issued two ``GET``s for one product. Worse than the cost, the
hash written to the lockfile came from a different ``desired()`` call than the
payload that went to Printify -- two answers that had to agree, kept in
agreement by hand. :class:`PlannedRun` carries them across instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from etsy_listings.engine.change import Plan, StagePlan
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.stage import AnyStage


@dataclass(frozen=True)
class StageState:
    """One stage, and the three states its ``plan()`` compared.

    Types erased, like :data:`AnyStage` -- the pipeline mixes stages with
    unrelated desired/live types by design (A1), and only the stage that
    produced them ever looks inside. ``applied`` is the exception: it is
    always the stage's raw lockfile subtree, since that is the form it was
    written in.
    """

    stage: AnyStage
    desired: Any
    applied: dict[str, Any] | None
    live: Any
    stage_plan: StagePlan


@dataclass(frozen=True)
class PlannedRun:
    """What ``plan`` produced, and what ``apply`` needs to act on it.

    ``plan`` is the presentation-facing half: ``cli.render`` formats it and the
    UI will serialise it, neither comparing state itself. ``states`` is the
    half only ``execute`` reads.
    """

    plan: Plan
    states: tuple[StageState, ...]


def build_plan(
    ctx: RunContext,
    listing: str,
    lock: Lockfile,
    stages: list[AnyStage],
) -> PlannedRun:
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
    states: list[StageState] = []
    for stage in stages:
        desired = stage.desired(ctx, listing)
        # The stage's own subtree, looked up here rather than by each stage
        # for itself -- a stage never needs to know which key in the lockfile
        # is its own, only how to read the document it finds there.
        applied = lock.applied_for(stage.name)
        live = stage.read_live(ctx, listing, lock)
        states.append(
            StageState(
                stage=stage,
                desired=desired,
                applied=applied,
                live=live,
                stage_plan=stage.plan(desired, applied, live),
            )
        )

    etsy_listing_id = lock.remote.get("etsy_listing_id")
    is_live = lock.remote.get("etsy_listing_state") not in (None, "draft")

    return PlannedRun(
        plan=Plan(
            listing=listing,
            is_live=is_live,
            etsy_listing_id=etsy_listing_id,
            stage_plans=tuple(state.stage_plan for state in states),
        ),
        states=tuple(states),
    )
