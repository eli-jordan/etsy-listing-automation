"""Retract a never-live listing: Printify DELETE, confirm the Etsy draft
went with it, then the run wipes local files (PRD 63).

Not in :data:`STAGES`. :func:`~etsy_listings.engine.lifecycle.walk` hands
this stage to ``build_plan`` *instead* of the pipeline when
``lifecycle: deleted`` is the right verb, so a listing we are about to
destroy is never rendered, PUT, or PATCHed -- updating it first is wasted
writes and a way to recreate a product ``read_live`` just said was missing.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from etsy_listings.engine.change import Action, Verdict
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile, StageApplyResult
from etsy_listings.engine.stage import Blocked
from etsy_listings.engine.stages.etsy_target import etsy_listing_id
from etsy_listings.engine.stages.printify_product import PRODUCT_ID_KEY
from etsy_listings.errors import UserFacingError


class AppliedRetract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    retracted: bool = True


@dataclass(frozen=True)
class RetractDesired:
    """Marker: this listing should have no remotes and then no files."""


@dataclass(frozen=True)
class RetractLive:
    product_id: str | None
    etsy_listing_id: int | None


class RetractStage:
    name = "retract"
    local = False
    applied_model = AppliedRetract

    def desired(
        self, ctx: RunContext, listing: str, applied: AppliedRetract | None
    ) -> RetractDesired | Blocked:
        del ctx, listing, applied
        return RetractDesired()

    def read_live(
        self, ctx: RunContext, listing: str, lock: Lockfile, applied: AppliedRetract | None
    ) -> RetractLive:
        del ctx, listing, applied
        raw_product = lock.remote.get(PRODUCT_ID_KEY)
        return RetractLive(
            product_id=str(raw_product) if raw_product else None,
            etsy_listing_id=etsy_listing_id(lock),
        )

    def plan(
        self,
        desired: RetractDesired,
        applied: AppliedRetract | None,
        live: RetractLive | None,
    ) -> Verdict:
        del desired, applied
        live = live or RetractLive(product_id=None, etsy_listing_id=None)
        actions: list[Action] = []
        if live.product_id is not None:
            actions.append(
                Action(description=f"DELETE Printify product {live.product_id} (still connected)")
            )
        if live.etsy_listing_id is not None:
            actions.append(
                Action(
                    description=(
                        f"GET Etsy listing {live.etsy_listing_id}; wipe local files on 404"
                    )
                )
            )
        actions.append(Action(description="wipe the listing directory and render cache"))
        return Verdict.work(
            "retract this listing's remotes, then wipe local files",
            actions=tuple(actions),
        )

    def apply(
        self,
        ctx: RunContext,
        desired: RetractDesired,
        applied: AppliedRetract | None,
        live: RetractLive | None,
        lock: Lockfile,
    ) -> StageApplyResult:
        del desired, applied
        live = live or RetractLive(
            product_id=(
                str(lock.remote[PRODUCT_ID_KEY]) if lock.remote.get(PRODUCT_ID_KEY) else None
            ),
            etsy_listing_id=etsy_listing_id(lock),
        )
        if live.product_id is not None:
            shop_id = ctx.workspace.defaults.printify.require_shop_id()
            ctx.emit(f"deleting Printify product {live.product_id}")
            ctx.require_printify().delete_product(shop_id, live.product_id)
        if live.etsy_listing_id is not None:
            ctx.emit(f"checking Etsy listing {live.etsy_listing_id} is gone")
            still = ctx.require_etsy().get_listing(live.etsy_listing_id)
            if still is not None:
                raise UserFacingError(
                    f"Etsy listing {live.etsy_listing_id} survived Printify DELETE.\n"
                    "Remove it in Shop Manager, then re-apply. Local files were "
                    "kept so the handle is not lost."
                )
        return StageApplyResult(applied=AppliedRetract().model_dump(mode="json"))
