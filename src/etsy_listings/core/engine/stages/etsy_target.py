"""Which listing, on which shop: the preamble the Etsy stages share."""

from __future__ import annotations

from dataclasses import dataclass

from etsy_listings.core.clients.etsy.listings import EtsyListingClient
from etsy_listings.core.engine.context import RunContext
from etsy_listings.core.engine.lock import Lockfile
from etsy_listings.core.engine.stage import Blocked

ETSY_LISTING_ID_KEY = "etsy_listing_id"
"""The Etsy listing id in ``lock.remote``. Written by `publish`, read by
`etsy_listing` and `etsy_media` -- which is why it is named here rather than in
the stage that happens to mint it."""

SHOP_REMEDY = "Run `etsy-listings setup`, then `etsy-listings auth`, to connect one."


@dataclass(frozen=True)
class EtsyListingTarget:
    client: EtsyListingClient
    shop_id: int
    listing_id: int


class EtsyListingNotMintedError(RuntimeError):
    """A wiring defect, not user-facing: `publish` runs first and either
    mints the id (ADR-0034) or raises."""

    def __init__(self, action: str) -> None:
        super().__init__(
            f"cannot {action}: no Etsy listing id on record. `publish` should have "
            f"minted one before this stage runs."
        )


def check_etsy_shop(ctx: RunContext, *, consequence: str) -> Blocked | None:
    """``consequence`` is what will not happen to this listing, from the
    user's side. Returns rather than raises: a raise would unwind the stage
    walk and take the other stages' plans with it."""
    if ctx.workspace.defaults.etsy.shop_id is not None:
        return None
    return Blocked(f"{consequence}: no Etsy shop is configured for this workspace.\n{SHOP_REMEDY}")


def etsy_listing_id(lock: Lockfile) -> int | None:
    listing_id = lock.remote.get(ETSY_LISTING_ID_KEY)
    if not listing_id:
        return None
    return int(listing_id)


def require_etsy_listing_id(lock: Lockfile, *, to: str) -> int:
    listing_id = etsy_listing_id(lock)
    if listing_id is None:
        raise EtsyListingNotMintedError(to)
    return listing_id
