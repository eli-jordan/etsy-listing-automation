"""The ``publish`` stage: asks Printify to push a product to the connected
Etsy shop, and polls until the resulting listing id exists.

Three things measured in
[docs/printify-etsy-integration.md](../../../../docs/printify-etsy-integration.md)
shape this stage:

- **The lock is real and asynchronous.** ``POST publish.json`` answers
  ``200 {}`` immediately; the actual work happens behind ``is_locked``, which
  cycled true -> false over roughly 8 seconds in the probe. So ``apply`` polls
  ``get_product`` rather than trusting the response.
- **``{variants: true}`` is safe; everything else stays false.** A forced
  divergence and republish proved copy, tags and media all survive a
  republish untouched -- this tool owns those, Printify should never sync
  them. ``shipping_template: false`` does not prevent Printify attaching its
  own profile (risk 13), but it is still sent, because a hint that sometimes
  works is better than no hint (decision 7) -- the `etsy_listing` stage is
  what actually re-asserts the shipping profile.
- **A retail price below Printify's cost is a `400`.** ``variants[].cost``
  only exists on a product that already exists, which is exactly what
  ``read_live`` has in hand by the time ``plan`` runs -- so the check lives in
  ``plan()``, turning a remote refusal into something `plan` can say before
  anything is sent (PRD 40's amendment).

The desired variant matrix is rebuilt through
:func:`~etsy_listings.engine.stages.printify_product.resolve_variant_pricing`,
the same pure resolution `printify_product` uses, rather than read out of that
stage's lockfile subtree -- decision 1's stage independence.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from etsy_listings.clients.printify.models import Product
from etsy_listings.clients.printify.protocol import PrintifyClient
from etsy_listings.config.money import Money
from etsy_listings.engine.change import Drift, Verdict
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.stage import Blocked, StageApplyResult
from etsy_listings.engine.stages.etsy_target import ETSY_LISTING_ID_KEY
from etsy_listings.engine.stages.gates import (
    check_copy_is_concrete,
    check_garment_profile_chosen,
)
from etsy_listings.engine.stages.printify_product import PRODUCT_ID_KEY, resolve_variant_pricing
from etsy_listings.engine.stages.product_document import AppliedVariant, PricedVariant, money
from etsy_listings.errors import UserFacingError

ETSY_LISTING_HANDLE_KEY = "etsy_listing_handle"
PUBLISH_LOCKED_KEY = "printify_publish_locked"
"""This stage's own keys in ``lock.remote`` (A20). The listing id it also
writes is named by ``etsy_target``, not here: two later stages read it, and a
key two stages read should not be spelled in the one that happens to mint
it."""

SYNC_FLAGS: dict[str, bool] = {
    "title": False,
    "description": False,
    "images": False,
    "variants": True,
    "tags": False,
    "keyFeatures": False,
    "shipping_template": False,
}
"""Fixed, not configurable per listing. Copy, tags and media are owned by
this tool's own stages and must never sync from Printify; the variant matrix
is the one thing Printify is allowed to push into Etsy, because a size or
price change made on the Printify side has nowhere else to go (the
production-cycle probe this policy is built on)."""

POLL_INITIAL_DELAY = 2.0
POLL_MAX_DELAY = 60.0
POLL_CEILING_SECONDS = 600.0
"""~10 minutes. The probe's own publish took ~8 seconds; this is headroom,
not an expectation."""

NO_SHOP_BLOCKED = Blocked(
    "this listing will not be published to Etsy: no Printify shop is "
    "configured for this workspace.\n"
    "Run `etsy-listings setup` to point it at one."
)


class PublishTimeoutError(UserFacingError, RuntimeError):
    """A publish that never cleared ``is_locked`` within the poll ceiling.

    The lock is real (measured); the remedy -- ``unlock`` -- has never been
    exercised against a genuine one, because none has stuck in probing. This
    still fails loudly rather than leaving the run waiting forever.
    """

    def __init__(self, product_id: str) -> None:
        super().__init__(
            f"Printify's publish for product {product_id} did not finish within "
            f"{int(POLL_CEILING_SECONDS // 60)} minutes, and the product is still locked.\n"
            f"Run `etsy-listings unlock <listing>` to clear the lock, then try again."
        )


class PublishWithoutProductError(UserFacingError, RuntimeError):
    """``apply`` was asked to publish a listing with no Printify product id
    on record. `printify_product` runs first in the pipeline and either mints
    one (available here via A26's same-run threading) or blocks -- reaching
    here means it blocked for a reason this stage's own gates do not share
    (a design too small, or a garment change), which is a real, if rare, gap
    between two independently-gated stages rather than a wiring defect.
    """

    def __init__(self) -> None:
        super().__init__(
            "cannot publish -- no Printify product exists for this listing yet. "
            "Check `plan` for why the printify_product stage did not create one."
        )


class PublishApplied(BaseModel):
    """The verbatim last-applied document (A2)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    sync_flags: dict[str, bool]
    variants: tuple[AppliedVariant, ...]

    @property
    def prices(self) -> dict[int, int]:
        return {variant.id: variant.price for variant in self.variants}


@dataclass(frozen=True)
class PublishDesired:
    sync_flags: dict[str, bool]
    priced_variants: tuple[PricedVariant, ...]
    """The full resolved matrix, colour and size included -- carried rather
    than collapsed straight to ``{id: price}`` because the below-cost
    snapshot (A30) needs to *name* a variant, not just its id, and this is
    the one place that resolution exists."""
    missing: tuple[tuple[str, str], ...] = ()
    currency: str = ""

    @property
    def variants(self) -> dict[int, int]:
        """``{variant_id: price}`` -- the shape every existing comparison
        here wants, and the only one variant identity does not survive a JSON
        round-trip as (see ``PrintifyProductDesired.prices`` for the same
        reasoning)."""
        return {variant.id: variant.price for variant in self.priced_variants}

    def applied(self) -> PublishApplied:
        return PublishApplied(
            sync_flags=self.sync_flags,
            variants=tuple(
                AppliedVariant(id=variant.id, price=variant.price, colour_slug=variant.colour_slug)
                for variant in sorted(self.priced_variants, key=lambda v: v.id)
            ),
        )


class BelowCostRow(BaseModel):
    """One variant priced under what Printify charges to make it -- the
    row `plan()` already refuses over (:func:`_below_cost`), named for the
    before/after review (A30) rather than left as a bare variant id."""

    model_config = ConfigDict(frozen=True)

    size: str
    colour: str
    price: Money
    cost: Money
    """USD, as Printify reports it -- not necessarily the listing's own
    currency (see :attr:`ProductVariant.cost`'s docstring). Shown as its own
    ``Money`` rather than coerced into ``price``'s currency, since the two
    can genuinely differ and a snapshot states facts, it does not convert
    them."""


class PublishSnapshot(BaseModel):
    """Domain facts for the review (A30): only the rows the stage's own
    ``plan()`` would refuse over, so the price table's red marker is never a
    second copy of the below-cost rule."""

    model_config = ConfigDict(frozen=True)

    below_cost: tuple[BelowCostRow, ...] = ()


@dataclass(frozen=True)
class PublishLive:
    external_id: str | None
    external_handle: str | None
    variant_costs: dict[int, int]
    """Enabled variants only -- the retail price this listing wants for one
    Printify has never priced is not a below-cost question."""


class PublishStage:
    name = "publish"
    local = False
    applied_model = PublishApplied

    def __init__(
        self,
        *,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
        poll_ceiling: float = POLL_CEILING_SECONDS,
    ) -> None:
        self._sleep = sleep
        self._now = now
        self._poll_ceiling = poll_ceiling

    def desired(
        self, ctx: RunContext, listing: str, applied: PublishApplied | None
    ) -> PublishDesired | Blocked:
        del applied
        if ctx.workspace.defaults.printify.shop_id is None:
            return NO_SHOP_BLOCKED

        config = ctx.workspace.load_listing(listing)
        # Before `resolve_variant_pricing` below, which loads the garment
        # profile this names -- the same gate the product stage runs, for the
        # same reason, since both reach that function.
        blocked = check_garment_profile_chosen(config.garment_profile)
        if blocked is not None:
            return blocked
        blocked = check_copy_is_concrete(
            title=config.etsy.title, description=config.etsy.description
        )
        if blocked is not None:
            return blocked

        resolved = resolve_variant_pricing(ctx, listing)
        return PublishDesired(
            sync_flags=SYNC_FLAGS,
            priced_variants=resolved.variants,
            missing=resolved.missing,
            currency=ctx.workspace.defaults.etsy.currency,
        )

    def read_live(
        self, ctx: RunContext, listing: str, lock: Lockfile, applied: PublishApplied | None
    ) -> PublishLive | None:
        """``None`` without a request when there is no product id yet --
        nothing to publish before `printify_product` has ever applied."""
        del applied
        product_id = lock.remote.get(PRODUCT_ID_KEY)
        if not product_id:
            return None
        product = ctx.require_printify().get_product(_shop_id(ctx), str(product_id))
        if product is None:
            return None
        return PublishLive(
            external_id=product.external.id if product.external else None,
            external_handle=product.external.handle if product.external else None,
            variant_costs={v.id: v.cost for v in product.variants if v.is_enabled},
        )

    def plan(
        self, desired: PublishDesired, applied: PublishApplied | None, live: PublishLive | None
    ) -> Verdict:
        drift = _drift(applied, live)

        if live is not None and live.variant_costs:
            shortfall = _below_cost(desired.variants, live.variant_costs)
            if shortfall:
                # A refusal, not a quiet no-op: `plan` renders this beside the
                # ones `desired()` raises. It cannot *be* one of those -- the
                # costs it needs arrive with `read_live` (PRD 40's amendment).
                return Verdict.refused(_below_cost_message(shortfall), drift=drift)

        if applied is None:
            return Verdict.work("publishing for the first time", drift=drift)
        if live is None or live.external_id is None:
            return Verdict.work(
                "the Printify product has no Etsy listing yet -- publishing", drift=drift
            )
        if desired.variants != applied.prices:
            return Verdict.work("the variant matrix differs from what Etsy has", drift=drift)
        return Verdict(will_run=False, drift=drift)

    def snapshot(self, desired: PublishDesired, live: PublishLive | None) -> PublishSnapshot:
        """The below-cost rows only, named (A30) -- reuses ``_below_cost``
        rather than re-deriving which variants are under cost, so the price
        table's red marker cannot drift from the rule ``plan()`` refuses
        with."""
        if live is None or not live.variant_costs:
            return PublishSnapshot()
        shortfall = _below_cost(desired.variants, live.variant_costs)
        by_id = {variant.id: variant for variant in desired.priced_variants}
        rows = tuple(
            BelowCostRow(
                size=by_id[variant_id].size,
                colour=by_id[variant_id].colour_slug,
                price=money(by_id[variant_id].price, desired.currency),
                cost=money(live.variant_costs[variant_id], "USD"),
            )
            for variant_id in shortfall
            if variant_id in by_id
        )
        return PublishSnapshot(below_cost=rows)

    def apply(
        self,
        ctx: RunContext,
        desired: PublishDesired,
        applied: PublishApplied | None,
        live: PublishLive | None,
        lock: Lockfile,
    ) -> StageApplyResult:
        del applied
        client = ctx.require_printify()
        shop_id = _shop_id(ctx)
        product_id = lock.remote.get(PRODUCT_ID_KEY)
        if not product_id:
            raise PublishWithoutProductError()

        ctx.emit(f"publishing product {product_id}")
        client.publish(shop_id, str(product_id), desired.sync_flags)
        product = self._poll_until_unlocked(client, shop_id, str(product_id))
        if product is None or product.external is None:
            raise PublishTimeoutError(str(product_id))

        ctx.emit(f"published as Etsy listing {product.external.id}")
        return StageApplyResult(
            applied=desired.applied().model_dump(mode="json"),
            remote={
                ETSY_LISTING_ID_KEY: int(product.external.id),
                ETSY_LISTING_HANDLE_KEY: product.external.handle,
                PUBLISH_LOCKED_KEY: False,
            },
        )

    def _poll_until_unlocked(
        self, client: PrintifyClient, shop_id: int, product_id: str
    ) -> Product | None:
        """Poll ``get_product`` until it is unlocked and carries ``external``,
        or the ceiling passes. ``None`` on timeout."""
        delay = POLL_INITIAL_DELAY
        deadline = self._now() + self._poll_ceiling
        while True:
            product = client.get_product(shop_id, product_id)
            if product is not None and not product.is_locked and product.external is not None:
                return product
            if self._now() >= deadline:
                return None
            self._sleep(delay)
            delay = min(delay * 2, POLL_MAX_DELAY)


def _shop_id(ctx: RunContext) -> int:
    return ctx.workspace.defaults.printify.require_shop_id()


def _drift(applied: PublishApplied | None, live: PublishLive | None) -> tuple[Drift, ...]:
    if applied is not None and live is not None and live.external_id is None:
        return (Drift(path="external", last_applied="published", live="not published"),)
    return ()


def _below_cost(desired_prices: dict[int, int], costs: dict[int, int]) -> tuple[int, ...]:
    return tuple(
        sorted(
            variant_id
            for variant_id, price in desired_prices.items()
            if variant_id in costs and price < costs[variant_id]
        )
    )


def _below_cost_message(variant_ids: tuple[int, ...]) -> str:
    """The consequence first, the remedy under it -- ``Blocked``'s shape, which
    ``cli.render`` relies on to indent one under the other."""
    listed = ", ".join(str(v) for v in variant_ids)
    return (
        f"this listing will not be published: the price for variant(s) {listed} is "
        f"below Printify's cost for them, and Printify refuses to publish below cost.\n"
        f"Raise the price in listing.yaml, or in the pricing plan it draws from."
    )
