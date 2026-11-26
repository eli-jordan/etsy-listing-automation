"""Retract a never-live listing: Printify DELETE, confirm the Etsy draft
went with it, then the run wipes local files.

Not in :data:`STAGES`. :func:`~etsy_listings.core.engine.lifecycle.walk` hands
this stage to ``build_plan`` *instead* of the pipeline when
``lifecycle: deleted`` is the right verb, so a listing we are about to
destroy is never rendered, PUT, or PATCHed -- updating it first is wasted
writes and a way to recreate a product ``read_live`` just said was missing.

The Etsy 404 is polled, not one GET: Etsy's read-after-write lags the cascade
(docs/features/listing-lifecycle-20260916/spec.md, *The cascade*).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from pydantic import BaseModel, ConfigDict

from etsy_listings.core.engine.change import Action, Verdict
from etsy_listings.core.engine.context import RunContext
from etsy_listings.core.engine.lock import Lockfile, StageApplyResult
from etsy_listings.core.engine.stage import Blocked, Stage
from etsy_listings.core.engine.stages.etsy_target import etsy_listing_id
from etsy_listings.core.engine.stages.printify_product import PRODUCT_ID_KEY
from etsy_listings.core.errors import UserFacingError

POLL_INITIAL_DELAY = 1.0
POLL_MAX_DELAY = 4.0
POLL_CEILING_SECONDS = 15.0
"""Short on purpose: this waits out read-after-write lag on a delete that
already happened, not an in-progress job like `publish`'s. A listing genuinely
left behind should fail promptly, not after minutes of retrying."""


class AppliedRetract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    retracted: bool = True


@dataclass(frozen=True)
class RetractDesired:
    pass


@dataclass(frozen=True)
class RetractLive:
    product_id: str | None
    etsy_listing_id: int | None


class RetractStage(Stage[RetractDesired, AppliedRetract, RetractLive]):
    name = "retract"
    local = False
    group: str | None = None
    applied_model = AppliedRetract

    def __init__(
        self,
        *,
        sleep: Callable[[float], None] | None = None,
        now: Callable[[], float] | None = None,
        poll_ceiling: float = POLL_CEILING_SECONDS,
    ) -> None:
        # Resolved here, not as a default-parameter value: `walk()` builds a
        # fresh instance on every call rather than holding a module-level
        # singleton, so a test that monkeypatches `time.sleep` before that
        # call needs this to be a live lookup, not a reference to whatever
        # `time.sleep` was when this module was first imported.
        self._sleep = sleep or time.sleep
        self._now = now or time.monotonic
        self._poll_ceiling = poll_ceiling

    @override
    def desired(
        self, ctx: RunContext, listing: str, applied: AppliedRetract | None
    ) -> RetractDesired | Blocked:
        del ctx, listing, applied
        return RetractDesired()

    @override
    def read_live(
        self, ctx: RunContext, listing: str, lock: Lockfile, applied: AppliedRetract | None
    ) -> RetractLive:
        del ctx, listing, applied
        raw_product = lock.remote.get(PRODUCT_ID_KEY)
        return RetractLive(
            product_id=str(raw_product) if raw_product else None,
            etsy_listing_id=etsy_listing_id(lock),
        )

    @override
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

    @override
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
            if not self._wait_for_gone(ctx, live.etsy_listing_id):
                raise UserFacingError(
                    f"Etsy listing {live.etsy_listing_id} survived Printify DELETE.\n"
                    "Remove it in Shop Manager, then re-apply. Local files were "
                    "kept so the handle is not lost."
                )
        return StageApplyResult(applied=AppliedRetract().model_dump(mode="json"))

    def _wait_for_gone(self, ctx: RunContext, listing_id: int) -> bool:
        delay = POLL_INITIAL_DELAY
        deadline = self._now() + self._poll_ceiling
        while True:
            if ctx.require_etsy().get_listing(listing_id) is None:
                return True
            if self._now() >= deadline:
                return False
            self._sleep(delay)
            delay = min(delay * 2, POLL_MAX_DELAY)
