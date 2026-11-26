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
    chosen_at_apply = True

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
