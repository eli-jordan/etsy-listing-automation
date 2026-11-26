from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from etsy_listings.core.engine.change import Plan, StagePlan
from etsy_listings.core.engine.context import RunContext
from etsy_listings.core.engine.events import (
    EngineEventSink,
    EngineStageChecking,
    EngineStagePlanned,
    ignore_engine_event,
)
from etsy_listings.core.engine.lifecycle import walk as lifecycle_walk
from etsy_listings.core.engine.lock import Lockfile
from etsy_listings.core.engine.stage import AnyStage, Blocked
from etsy_listings.core.engine.stages.etsy_target import etsy_listing_id


@dataclass(frozen=True)
class StageState:
    """One stage, and the three states its ``plan()`` compared.

    Types erased, like :data:`AnyStage` -- the pipeline mixes stages with
    unrelated desired/applied/live types by design, and only the stage
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
    decision = lifecycle_walk(ctx, listing, lock, stages)
    if decision.blocked is not None:
        planned = _all_blocked(
            listing, lock, decision.stages, decision.blocked, published=decision.published
        )
        for state in planned.states:
            on_event(EngineStageChecking(listing, state.stage.name))
            on_event(EngineStagePlanned(listing, state.stage_plan))
        return planned
    states: list[StageState] = []
    for stage in decision.stages:
        held = _held_by_earlier_block(stage, states)
        if held is not None:
            state = held
            on_event(EngineStageChecking(listing, stage.name))
            on_event(EngineStagePlanned(listing, state.stage_plan))
            states.append(state)
            continue
        state = _walk(ctx, listing, lock, stage, on_event=on_event)
        states.append(state)
        rewrites = _rewrites(ctx, state)
        if rewrites:
            ctx = replace(ctx, rewrites={**ctx.rewrites, **rewrites})

    return _assemble(
        listing,
        lock,
        tuple(states),
        published=decision.published,
        publishable=decision.activatable and not _blocked(states),
    )


def _blocked(states: list[StageState]) -> bool:
    return any(
        state.stage_plan.blocked is not None
        for state in states
        if not state.stage_plan.chosen_at_apply
    )


def _held_by_earlier_block(stage: AnyStage, earlier: list[StageState]) -> StageState | None:
    """A stage that declares ``needs_every_earlier_stage`` is blocked, without
    being asked, while any stage before it is. ``etsy_activate`` is the one:
    publishing a listing whose images could not be uploaded would show buyers
    Printify's mockups."""
    if not stage.needs_every_earlier_stage:
        return None
    blocker = next((state for state in earlier if state.stage_plan.blocked is not None), None)
    if blocker is None:
        return None
    message = (
        f"this listing will stay a draft on Etsy: the {blocker.stage.name} stage is blocked.\n"
        f"Fix what {blocker.stage.name} reports, then apply again."
    )
    return StageState(
        stage=stage,
        desired=Blocked(message),
        applied=None,
        live=None,
        stage_plan=StagePlan.block(
            stage.name, message, group=stage.group, chosen_at_apply=stage.chosen_at_apply
        ),
    )


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
            stage_plan=StagePlan.block(
                stage.name, message, group=stage.group, chosen_at_apply=stage.chosen_at_apply
            ),
        )
        for stage in stages
    )
    return _assemble(listing, lock, states, published=published)


def _walk(
    ctx: RunContext, listing: str, lock: Lockfile, stage: AnyStage, *, on_event: EngineEventSink
) -> StageState:
    on_event(EngineStageChecking(listing, stage.name))
    applied = lock.parse_applied_for(stage.name, stage.applied_model)
    desired = stage.desired(ctx, listing, applied)

    if isinstance(desired, Blocked):
        state = StageState(
            stage=stage,
            desired=desired,
            applied=applied,
            live=None,
            stage_plan=StagePlan.block(
                stage.name,
                desired.message,
                group=stage.group,
                chosen_at_apply=stage.chosen_at_apply,
            ),
        )
        on_event(EngineStagePlanned(listing, state.stage_plan))
        return state

    live = stage.read_live(ctx, listing, lock, applied)
    verdict = stage.plan(desired, applied, live)
    stage_plan = StagePlan(
        stage=stage.name,
        outcome=verdict.outcome,
        drift=verdict.drift,
        snapshot=stage.snapshot(desired, live),
        group=stage.group,
        review_hash=stage.review_hash(desired),
        chosen_at_apply=stage.chosen_at_apply,
    )
    state = StageState(
        stage=stage, desired=desired, applied=applied, live=live, stage_plan=stage_plan
    )
    on_event(EngineStagePlanned(listing, stage_plan))
    return state


def _rewrites(ctx: RunContext, state: StageState) -> Mapping[Path, Path | None]:
    if not state.stage_plan.will_run:
        return {}
    return state.stage.rewrites(ctx, state.desired, state.live)


def _assemble(
    listing: str,
    lock: Lockfile,
    states: tuple[StageState, ...],
    *,
    published: bool,
    publishable: bool = False,
) -> PlannedRun:
    return PlannedRun(
        plan=Plan(
            listing=listing,
            is_live=published,
            etsy_listing_id=etsy_listing_id(lock),
            stage_plans=tuple(state.stage_plan for state in states),
            publishable=publishable,
        ),
        states=tuple(states),
    )
