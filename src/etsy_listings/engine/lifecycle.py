"""Listing-level lifecycle orchestration (PRD 61–67).

Delete, retire and renew are one product concept, and they used to be a
scavenger hunt: ``plan`` chose the pipeline, ``run`` wiped files and edited
``lifecycle: renew`` out of the yaml, ``Plan.is_live`` read a lockfile key no
stage writes, and the listings DELETE reconstructed "published?" from a
different predicate. The copies could not even be compared in production,
because one never saw a value.

This module owns the questions those call sites were each answering:

* which stages to walk (retract-only, the normal pipeline, or all blocked)
* whether the listing has left Etsy ``draft`` -- one GET, one fact
* what to do after a successful apply (wipe, or consume ``renew``)

It does **not** own the retract stage's HTTP, ``listing_validation``'s
sentences, or the pure badge table in ``status.py``. ``Plan.is_live`` is this
module's published fact, threaded through ``build_plan``; a key that does not
exist is not a fact.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import yaml

from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.stage import AnyStage
from etsy_listings.engine.stages.etsy_target import etsy_listing_id
from etsy_listings.engine.stages.gates import check_lifecycle_verb, check_listing_yaml_present
from etsy_listings.engine.stages.retract import RetractStage
from etsy_listings.engine.status import is_live_etsy_state

if TYPE_CHECKING:
    from etsy_listings.engine.plan import PlannedRun

UNREADABLE_ETSY = (
    "this listing has an Etsy id but this run cannot read it, so "
    "delete/retire cannot be proven safe.\n"
    "Connect Etsy (`etsy-listings auth`) and re-run."
)


@dataclass(frozen=True)
class LifecycleWalk:
    """What this listing's lifecycle does to a plan.

    ``blocked`` wraps the walk rather than living in any one stage: missing
    yaml, the wrong verb, or a delete/retire we cannot prove safe. ``stages``
    in that case is the pipeline the caller passed, so every stage shows the
    same refusal. Otherwise it is either that pipeline or ``RetractStage``
    alone.
    """

    stages: list[AnyStage]
    published: bool
    blocked: str | None = None


def published_on_etsy(ctx: RunContext, lock: Lockfile) -> bool | None:
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


def walk(
    ctx: RunContext,
    listing: str,
    lock: Lockfile,
    stages: Sequence[AnyStage],
) -> LifecycleWalk:
    """Missing yaml, wrong verb, or retract-only -- listing-level, so they
    wrap the walk rather than living in any one stage (PRD 61–67)."""
    pipeline = list(stages)
    present = ctx.workspace.listing_file(listing).is_file()
    if not present:
        # PRD 67: yaml gone, lockfile still there -- the row appears, Blocked.
        # No directory at all is not that: it is an unknown listing, and
        # load_listing raises the same ConfigLoadError it always did.
        if not ctx.workspace.lock_file(listing).is_file():
            ctx.workspace.load_listing(listing)
        yaml_block = check_listing_yaml_present(present=False)
        if yaml_block is not None:
            return LifecycleWalk(stages=pipeline, published=False, blocked=yaml_block.message)

    config = ctx.workspace.load_listing(listing)
    published = published_on_etsy(ctx, lock)
    if published is None and config.lifecycle in {"deleted", "retired"}:
        return LifecycleWalk(stages=pipeline, published=False, blocked=UNREADABLE_ETSY)
    proven = False if published is None else published
    verb_block = check_lifecycle_verb(config.lifecycle, published=proven)
    if verb_block is not None:
        return LifecycleWalk(stages=pipeline, published=proven, blocked=verb_block.message)
    if config.lifecycle == "deleted":
        return LifecycleWalk(stages=[RetractStage()], published=proven)
    return LifecycleWalk(stages=pipeline, published=proven)


def after_apply(ctx: RunContext, listing: str, planned: PlannedRun) -> None:
    """The listing-level half of a successful apply: wipe after retract, or
    consume ``lifecycle: renew``. ``plan`` never writes the yaml."""
    if _retract_succeeded(planned):
        ctx.workspace.remove_listing(listing)
        return
    _omit_consumed_renew(ctx, listing, planned)


def _retract_succeeded(planned: PlannedRun) -> bool:
    return any(
        state.stage.name == "retract" and state.stage_plan.will_run for state in planned.states
    )


def _omit_consumed_renew(ctx: RunContext, listing: str, planned: PlannedRun) -> None:
    """``lifecycle: renew`` is a one-shot mark (PRD 62). Apply sends
    ``state=active``, then deletes the key."""
    etsy_plan = next(
        (sp for sp in planned.plan.stage_plans if sp.stage == "etsy_listing"),
        None,
    )
    if etsy_plan is None or etsy_plan.blocked is not None:
        return
    path = ctx.workspace.listing_file(listing)
    if not path.is_file():
        return
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if raw.get("lifecycle") != "renew":
        return
    del raw["lifecycle"]
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
