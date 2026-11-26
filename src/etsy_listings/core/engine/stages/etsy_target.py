"""Which listing, on which shop: the preamble the Etsy stages share.

:class:`~etsy_listings.core.engine.stages.publish.PublishWithoutProductError`
stays separate: it is about the Printify product id, and it is a
:class:`~etsy_listings.core.errors.UserFacingError` rather than a wiring defect.
"""

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
    """``apply`` reached an Etsy stage with no listing id on record.

    `publish` runs first in the pipeline and either mints one -- visible here
    the same run via ADR-0034's threading of ``lock.remote`` -- or raises. Reaching
    this is a wiring defect, not a configuration problem, so it is not
    user-facing and gets the traceback a defect deserves.

    ``action`` is the caller's own verb, so the message says which stage's
    work did not happen without the message having to be written twice.
    """

    def __init__(self, action: str) -> None:
        super().__init__(
            f"cannot {action}: no Etsy listing id on record. `publish` should have "
            f"minted one before this stage runs."
        )


def check_etsy_shop(ctx: RunContext, *, consequence: str) -> Blocked | None:
    """Refuse a workspace that has never been pointed at an Etsy shop.

    ``consequence`` is what will not happen to *this listing*, phrased from
    the user's side -- "this listing's images will not be uploaded to Etsy".
    The cause and the remedy are this module's, and identical for every
    caller, which is the half that drifted when each stage wrote its own.

    Returns rather than raises, per ``gates``: a refusal is something `plan`
    reports, and one that unwinds the stage walk takes the other stages'
    plans with it.
    """
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
