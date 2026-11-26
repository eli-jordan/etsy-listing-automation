"""Listing-level lifecycle: which stages delete, retire and renew walk, whether
the listing has left Etsy ``draft``, and what follows a successful apply."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from etsy_listings.core.engine.context import RunContext
from etsy_listings.core.engine.lock import Lockfile
from etsy_listings.core.engine.stage import AnyStage
from etsy_listings.core.engine.stages.etsy_target import etsy_listing_id
from etsy_listings.core.engine.stages.gates import check_lifecycle_verb, check_listing_yaml_present
from etsy_listings.core.engine.stages.retract import RetractStage
from etsy_listings.core.engine.status import is_live_etsy_state
from etsy_listings.core.listing_artifacts import remove_listing
from etsy_listings.core.workspace.listing_documents import (
    Document,
    ListingDocuments,
    ListingMissingError,
)

if TYPE_CHECKING:
    from etsy_listings.core.engine.plan import PlannedRun

UNREADABLE_ETSY = (
    "this listing has an Etsy id but this run cannot read it, so "
    "delete/retire cannot be proven safe.\n"
    "Connect Etsy (`etsy-listings auth`) and re-run."
)


@dataclass(frozen=True)
class LifecycleWalk:
    """The caller's pipeline, ``RetractStage`` alone, or a ``blocked``
    refusal every stage carries."""

    stages: list[AnyStage]
    published: bool
    blocked: str | None = None
    activatable: bool = False
    """An opt-in publish could activate it: still an Etsy draft or not on
    Etsy yet, with no ``lifecycle`` verb. ``build_plan`` adds the condition
    that no stage is blocked."""


EtsyPublication = Literal["live", "never_live", "unknown"]
"""``unknown``: an Etsy id but no client to ask, so delete/retire fails closed.
No id is ``never_live``, including a Printify-only product."""


def published_on_etsy(ctx: RunContext, lock: Lockfile) -> EtsyPublication:
    listing_id = etsy_listing_id(lock)
    if listing_id is None:
        return "never_live"
    if ctx.etsy is None:
        return "unknown"
    live = ctx.etsy.get_listing(listing_id)
    if live is None or live.state is None or not is_live_etsy_state(live.state):
        return "never_live"
    return "live"


def walk(
    ctx: RunContext,
    listing: str,
    lock: Lockfile,
    stages: Sequence[AnyStage],
) -> LifecycleWalk:
    pipeline = list(stages)
    present = ListingDocuments(ctx.workspace).exists(listing)
    if not present:
        # yaml gone, lockfile still there: the row appears, Blocked. With
        # neither it is an unknown listing and load_listing raises.
        if not ctx.workspace.lock_file(listing).is_file():
            ctx.workspace.load_listing(listing)
        yaml_block = check_listing_yaml_present(present=False)
        if yaml_block is not None:
            return LifecycleWalk(stages=pipeline, published=False, blocked=yaml_block.message)

    config = ctx.workspace.load_listing(listing)
    publication = published_on_etsy(ctx, lock)
    if publication == "unknown" and config.lifecycle in {"deleted", "retired"}:
        return LifecycleWalk(stages=pipeline, published=False, blocked=UNREADABLE_ETSY)
    proven = publication == "live"
    verb_block = check_lifecycle_verb(config.lifecycle, published=proven)
    if verb_block is not None:
        return LifecycleWalk(stages=pipeline, published=proven, blocked=verb_block.message)
    if config.lifecycle == "deleted":
        return LifecycleWalk(stages=[RetractStage()], published=proven)
    return LifecycleWalk(
        stages=pipeline,
        published=proven,
        activatable=not proven and config.lifecycle is None,
    )


def after_apply(ctx: RunContext, listing: str, planned: PlannedRun) -> None:
    if _retract_succeeded(planned):
        remove_listing(ctx.workspace, listing)
        return
    _omit_consumed_renew(ctx, listing, planned)


def _retract_succeeded(planned: PlannedRun) -> bool:
    return any(
        state.stage.name == "retract" and state.stage_plan.will_run for state in planned.states
    )


def _omit_consumed_renew(ctx: RunContext, listing: str, planned: PlannedRun) -> None:
    etsy_plan = next(
        (sp for sp in planned.plan.stage_plans if sp.stage == "etsy_listing"),
        None,
    )
    if etsy_plan is None or etsy_plan.blocked is not None:
        return
    with suppress(ListingMissingError):
        ListingDocuments(ctx.workspace).edit(listing, _without_renew)


def _without_renew(raw: Document) -> Document | None:
    if raw.get("lifecycle") != "renew":
        return None
    return {key: value for key, value in raw.items() if key != "lifecycle"}
