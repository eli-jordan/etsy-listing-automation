"""The ``etsy_activate`` stage: publish a still-draft Etsy listing, when the
seller asked this run to.

Not in :data:`~etsy_listings.core.engine.stages.STAGES`. A first apply leaves
an Etsy ``draft`` and that stays the default; a run opts in with
:func:`~etsy_listings.core.engine.stages.publishing_pipeline`, which appends
this stage after every other one. Last, because activation is the moment a
buyer can see the listing: the copy, the images and the videos all have to be
on it first, not Printify's own mockups.

Only a ``draft`` is ever activated. ``inactive`` is a listing the seller
paused, or one retired here, and ``lifecycle`` has its own verbs for those; a
listing whose yaml names a ``lifecycle`` is left to them. Etsy activates a
draft through the same ``PATCH updateListing`` the ``etsy_listing`` stage
sends, with ``state=active`` (that stage strips ``state`` on a draft, so the
two never disagree about who activates).

The stage declares ``needs_every_earlier_stage``: ``build_plan`` blocks it
when any stage before it is blocked, because publishing a listing whose
images could not be uploaded would put Printify's mockups in front of buyers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from pydantic import BaseModel, ConfigDict

from etsy_listings.core.clients.etsy import models as etsy_models
from etsy_listings.core.engine.change import Verdict
from etsy_listings.core.engine.stage import Blocked, Stage, StageApplyResult
from etsy_listings.core.engine.stages.etsy_target import (
    check_etsy_shop,
    etsy_listing_id,
    require_etsy_listing_id,
)

if TYPE_CHECKING:
    from etsy_listings.core.engine.context import RunContext
    from etsy_listings.core.engine.lock import Lockfile

STAGE_NAME = "etsy_activate"


class EtsyActivateApplied(BaseModel):
    """The verbatim last-applied document: the listing was activated."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    state: str = "active"


@dataclass(frozen=True)
class EtsyActivateDesired:
    lifecycle: str | None
    """The listing's ``lifecycle`` verb. Any verb leaves activation alone."""


class EtsyActivateStage(Stage[EtsyActivateDesired, EtsyActivateApplied, etsy_models.Listing]):
    name = STAGE_NAME
    local = False
    group: str | None = None
    applied_model = EtsyActivateApplied
    needs_every_earlier_stage = True

    @override
    def desired(
        self, ctx: RunContext, listing: str, applied: EtsyActivateApplied | None
    ) -> EtsyActivateDesired | Blocked:
        del applied
        blocked = check_etsy_shop(ctx, consequence="this listing will not be published on Etsy")
        if blocked is not None:
            return blocked
        return EtsyActivateDesired(lifecycle=ctx.workspace.load_listing(listing).lifecycle)

    @override
    def read_live(
        self,
        ctx: RunContext,
        listing: str,
        lock: Lockfile,
        applied: EtsyActivateApplied | None,
    ) -> etsy_models.Listing | None:
        """``None`` without a request when there is no Etsy listing yet: the
        ``publish`` stage creates it as a draft earlier in this same run."""
        del applied
        listing_id = etsy_listing_id(lock)
        if listing_id is None:
            return None
        return ctx.require_etsy().get_listing(listing_id)

    @override
    def plan(
        self,
        desired: EtsyActivateDesired,
        applied: EtsyActivateApplied | None,
        live: etsy_models.Listing | None,
    ) -> Verdict:
        del applied
        if desired.lifecycle is not None:
            return Verdict.no_work()
        if live is None:
            return Verdict.work("new listing -- publishing it on Etsy instead of leaving a draft")
        if live.state == "draft":
            return Verdict.work("still an Etsy draft -- publishing it")
        return Verdict.no_work()

    @override
    def apply(
        self,
        ctx: RunContext,
        desired: EtsyActivateDesired,
        applied: EtsyActivateApplied | None,
        live: etsy_models.Listing | None,
        lock: Lockfile,
    ) -> StageApplyResult:
        del desired, applied, live
        listing_id = require_etsy_listing_id(lock, to="publish the listing")
        shop_id = ctx.workspace.defaults.etsy.require_shop_id()
        ctx.emit(f"publishing Etsy listing {listing_id}")
        ctx.require_etsy().update_listing(shop_id, listing_id, {"state": "active"})
        return StageApplyResult(applied=EtsyActivateApplied().model_dump(mode="json"))
