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

from etsy_listings.engine.change import Plan, StagePlan
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.stage import AnyStage, Blocked
from etsy_listings.engine.stages.etsy_target import etsy_listing_id
from etsy_listings.engine.stages.gates import check_lifecycle_verb, check_listing_yaml_present
from etsy_listings.engine.stages.retract import RetractStage
from etsy_listings.engine.status import is_live_etsy_state


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
    walk = _stages_for_lifecycle(ctx, listing, lock, stages)
    if isinstance(walk, PlannedRun):
        return walk
    states = [_walk(ctx, listing, lock, stage) for stage in walk]

    return _assemble(listing, lock, tuple(states))


def _stages_for_lifecycle(
    ctx: RunContext,
    listing: str,
    lock: Lockfile,
    stages: list[AnyStage],
) -> list[AnyStage] | PlannedRun:
    """Missing yaml, wrong verb, or retract-only -- listing-level, so they
    wrap the walk rather than living in any one stage (PRD 61–67)."""
    present = ctx.workspace.listing_file(listing).is_file()
    if not present:
        # PRD 67: yaml gone, lockfile still there -- the row appears, Blocked.
        # No directory at all is not that: it is an unknown listing, and
        # load_listing raises the same ConfigLoadError it always did.
        if not ctx.workspace.lock_file(listing).is_file():
            ctx.workspace.load_listing(listing)
        yaml_block = check_listing_yaml_present(present=False)
        if yaml_block is not None:
            return _all_blocked(listing, lock, stages, yaml_block.message)

    config = ctx.workspace.load_listing(listing)
    published = _published_on_etsy(ctx, lock)
    if published is None and config.lifecycle in {"deleted", "retired"}:
        return _all_blocked(
            listing,
            lock,
            stages,
            "this listing has an Etsy id but this run cannot read it, so "
            "delete/retire cannot be proven safe.\n"
            "Connect Etsy (`etsy-listings auth`) and re-run.",
        )
    verb_block = check_lifecycle_verb(
        config.lifecycle, published=False if published is None else published
    )
    if verb_block is not None:
        return _all_blocked(listing, lock, stages, verb_block.message)
    if config.lifecycle == "deleted":
        return [RetractStage()]
    return stages


def _published_on_etsy(ctx: RunContext, lock: Lockfile) -> bool | None:
    """Whether the listing has left Etsy ``draft``.

    ``None`` means we have an id but no client to ask -- delete/retire must
    not guess; the caller fails closed. No id is never-live (``False``),
    including a Printify-only product.
    """
    listing_id = etsy_listing_id(lock)
    if listing_id is None:
        return False
    if ctx.etsy is None:
        return None
    live = ctx.etsy.get_listing(listing_id)
    if live is None or live.state is None:
        return False
    return is_live_etsy_state(live.state)


def _all_blocked(listing: str, lock: Lockfile, stages: list[AnyStage], message: str) -> PlannedRun:
    states = tuple(
        StageState(
            stage=stage,
            desired=Blocked(message),
            applied=None,
            live=None,
            stage_plan=StagePlan(stage=stage.name, will_run=False, blocked=message),
        )
        for stage in stages
    )
    return _assemble(listing, lock, states)


def _walk(ctx: RunContext, listing: str, lock: Lockfile, stage: AnyStage) -> StageState:
    """One stage's three states, and the plan comparing them.

    Every line of bookkeeping a stage used to do for itself lives here: the
    subtree lookup, the decode, the refusal, and the stage's own name. What
    the stage is left with is three questions about three states.
    """
    # The stage's own subtree, looked up and decoded here rather than by each
    # stage for itself -- a stage never needs to know which key in the
    # lockfile is its own, nor what a document it cannot read should mean.
    applied = lock.parse_applied_for(stage.name, stage.applied_model)
    desired = stage.desired(ctx, listing, applied)

    if isinstance(desired, Blocked):
        # Refused: no live read, because there is nothing this run could do
        # with the answer, and a blocked remote stage should not spend a
        # request finding that out.
        return StageState(
            stage=stage,
            desired=desired,
            applied=applied,
            live=None,
            stage_plan=StagePlan(stage=stage.name, will_run=False, blocked=desired.message),
        )

    live = stage.read_live(ctx, listing, lock, applied)
    verdict = stage.plan(desired, applied, live)
    return StageState(
        stage=stage,
        desired=desired,
        applied=applied,
        live=live,
        stage_plan=StagePlan(
            stage=stage.name,
            will_run=verdict.will_run,
            changes=verdict.changes,
            drift=verdict.drift,
            reason=verdict.reason,
            actions=verdict.actions,
            # A refusal is a refusal whichever question produced it: one the
            # live state proved lands in the same field as one `desired()`
            # raised, so `cli.render` and the UI's serialiser show it without
            # knowing there were ever two routes to it.
            blocked=verdict.refusal,
        ),
    )


def _assemble(listing: str, lock: Lockfile, states: tuple[StageState, ...]) -> PlannedRun:
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
