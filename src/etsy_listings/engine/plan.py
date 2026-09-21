"""Builds a :class:`Plan` by walking the stage pipeline. A1/A2/A3.

Only this module (and ``apply``) may compute a diff -- the CLI renderer and the
UI's future JSON serialiser both consume the resulting :class:`Plan` /
:class:`StagePlan` / ``Change`` objects without comparing state themselves. That
is what keeps the CLI and UI enforcing identical rules.

Planning **keeps** what it resolved. It used to hand back the ``Plan`` alone
and drop the desired and live states it had just built, so ``execute`` asked
every stage for them a second time: one ``apply`` parsed the listing and its
garment profile five times over, hashed every design four times, resolved the variant
matrix twice and issued two ``GET``s for one product. Worse than the cost, the
hash written to the lockfile came from a different ``desired()`` call than the
payload that went to Printify -- two answers that had to agree, kept in
agreement by hand. :class:`PlannedRun` carries them across instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from etsy_listings.engine.change import Plan, StagePlan
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.events import (
    EngineEventSink,
    EngineStageChecking,
    EngineStagePlanned,
    ignore_engine_event,
)
from etsy_listings.engine.lifecycle import walk as lifecycle_walk
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.stage import AnyStage, Blocked
from etsy_listings.engine.stages.etsy_target import etsy_listing_id


@dataclass(frozen=True)
class StageState:
    """One stage, and the three states its ``plan()`` compared.

    Types erased, like :data:`AnyStage` -- the pipeline mixes stages with
    unrelated desired/applied/live types by design (A1), and only the stage
    that produced them ever looks inside.

    ``desired`` is the exception worth naming: it is a ``Blocked`` rather than
    a desired document when the stage refused, which is exactly the case
    ``stage_plan.blocked`` reports and ``execute`` never runs.
    """

    stage: AnyStage
    desired: Any
    applied: Any
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
    *,
    on_event: EngineEventSink = ignore_engine_event,
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

    ``on_event`` (A33) emits ``EngineStageChecking`` before each stage's own
    walk and ``EngineStagePlanned`` after it, with the resolved ``StagePlan``
    -- snapshot included -- so a caller watching a plan run (the UI's, in a
    later PR) can show one stage resolving after another, in pipeline order,
    rather than pretending A3's fan-out exists (A21 stands). ``None`` -- the
    default every existing caller gets -- is a plain walk with nothing
    watching; a listing wrapped wholesale in ``_all_blocked`` still reports
    each stage's block through the same two calls, since a blocked stage is
    still a stage the strip has to show.
    """
    decision = lifecycle_walk(ctx, listing, lock, stages)
    if decision.blocked is not None:
        planned = _all_blocked(
            listing, lock, decision.stages, decision.blocked, published=decision.published
        )
        for state in planned.states:
            on_event(EngineStageChecking(listing, state.stage.name))
            on_event(EngineStagePlanned(listing, state.stage_plan))
        return planned
    states = [_walk(ctx, listing, lock, stage, on_event=on_event) for stage in decision.stages]

    return _assemble(listing, lock, tuple(states), published=decision.published)


def _all_blocked(
    listing: str,
    lock: Lockfile,
    stages: list[AnyStage],
    message: str,
    *,
    published: bool,
) -> PlannedRun:
    states = tuple(
        StageState(
            stage=stage,
            desired=Blocked(message),
            applied=None,
            live=None,
            stage_plan=StagePlan.block(stage.name, message),
        )
        for stage in stages
    )
    return _assemble(listing, lock, states, published=published)


def _walk(
    ctx: RunContext, listing: str, lock: Lockfile, stage: AnyStage, *, on_event: EngineEventSink
) -> StageState:
    """One stage's three states, and the plan comparing them.

    Every line of bookkeeping a stage used to do for itself lives here: the
    subtree lookup, the decode, the refusal, and the stage's own name. What
    the stage is left with is three questions about three states.
    """
    on_event(EngineStageChecking(listing, stage.name))
    # The stage's own subtree, looked up and decoded here rather than by each
    # stage for itself -- a stage never needs to know which key in the
    # lockfile is its own, nor what a document it cannot read should mean.
    applied = lock.parse_applied_for(stage.name, stage.applied_model)
    desired = stage.desired(ctx, listing, applied)

    if isinstance(desired, Blocked):
        # Refused: no live read, because there is nothing this run could do
        # with the answer, and a blocked remote stage should not spend a
        # request finding that out. No snapshot either -- there is no desired
        # document a snapshot could be a fact about (A30).
        state = StageState(
            stage=stage,
            desired=desired,
            applied=applied,
            live=None,
            stage_plan=StagePlan.block(stage.name, desired.message),
        )
        on_event(EngineStagePlanned(listing, state.stage_plan))
        return state

    live = stage.read_live(ctx, listing, lock, applied)
    verdict = stage.plan(desired, applied, live)
    stage_plan = StagePlan(
        stage=stage.name,
        outcome=verdict.outcome,
        drift=verdict.drift,
        snapshot=_snapshot(stage, desired, live),
    )
    state = StageState(
        stage=stage, desired=desired, applied=applied, live=live, stage_plan=stage_plan
    )
    on_event(EngineStagePlanned(listing, stage_plan))
    return state


def _snapshot(stage: AnyStage, desired: Any, live: Any) -> BaseModel | None:
    """A stage's optional ``snapshot()`` (A30).

    Not part of ``Stage``'s formal surface (see ``stage.py``'s note on why),
    so looked up rather than called directly: a stage without one --
    ``render`` and ``retract``, for now -- simply has nothing to ask.
    """
    method = getattr(stage, "snapshot", None)
    if method is None:
        return None
    result: BaseModel | None = method(desired, live)
    return result


def _assemble(
    listing: str, lock: Lockfile, states: tuple[StageState, ...], *, published: bool
) -> PlannedRun:
    return PlannedRun(
        plan=Plan(
            listing=listing,
            is_live=published,
            etsy_listing_id=etsy_listing_id(lock),
            stage_plans=tuple(state.stage_plan for state in states),
        ),
        states=tuple(states),
    )
