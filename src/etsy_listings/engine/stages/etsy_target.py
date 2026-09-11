"""Which listing, on which shop -- the preamble all three Etsy stages share.

`publish` mints the Etsy listing id; `etsy_listing` and `etsy_media` both
PATCH it. So three stages need the same two facts before they can do anything,
and each had written out its own answer to both: four ``lock.remote.get(...)``
lookups with a hand-written falsy check, two shop gates, and three
near-identical "no id on record" errors.

The copies had already drifted, in the way a copied refusal always does.
``Blocked``'s contract is that the first line is the consequence in the user's
terms and any further lines are the remedy -- ``cli.render`` indents one under
the other -- and one of the two shop refusals opened with the *cause* instead
("no Etsy shop is configured..."), so it rendered as a fact about the
workspace where its neighbour rendered as a fact about the listing. Building
the sentence from the caller's own phrase makes that shape structural rather
than remembered.

This module lives beside :mod:`~etsy_listings.engine.stages.gates` on the same
argument: it is stage-level knowledge that belongs to no single stage. It owns
:data:`ETSY_LISTING_ID_KEY` for the same reason -- the key was `publish`'s only
by accident of who writes it first, and two stages that merely *read* it had
to import from the stage that does (A20 still holds: the ``etsy_*`` prefix is
this module's, and `publish` is still the only writer).

:class:`~etsy_listings.engine.stages.publish.PublishWithoutProductError` is
deliberately not folded in here, despite looking like a third copy. It is
about the *Printify* product id, it is a
:class:`~etsy_listings.errors.UserFacingError` rather than a wiring defect,
and it names a genuine gap between two independently-gated stages -- three
differences that the shared shape would flatten.
"""

from __future__ import annotations

from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.stage import Blocked

ETSY_LISTING_ID_KEY = "etsy_listing_id"
"""The Etsy listing id in ``lock.remote`` (A20). Written by `publish`, read by
`etsy_listing` and `etsy_media` -- which is why it is named here rather than in
the stage that happens to mint it."""

SHOP_REMEDY = "Run `etsy-listings setup`, then `etsy-listings auth`, to connect one."


class EtsyListingNotMintedError(RuntimeError):
    """``apply`` reached an Etsy stage with no listing id on record.

    `publish` runs first in the pipeline and either mints one -- visible here
    the same run via A26's threading of ``lock.remote`` -- or raises. Reaching
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
    """The listing `publish` minted, or ``None`` before it ever has.

    ``None`` rather than a raise because both readers have a legitimate
    nothing-to-do answer at plan time: ``read_live`` returns ``None`` without
    spending a request on a listing that does not exist yet.
    """
    listing_id = lock.remote.get(ETSY_LISTING_ID_KEY)
    if not listing_id:
        return None
    return int(listing_id)


def require_etsy_listing_id(lock: Lockfile, *, to: str) -> int:
    """The listing id, or a loud failure -- ``apply``'s half of the question.

    ``to`` completes "cannot {to}", so each stage names its own work while the
    diagnosis stays written once.
    """
    listing_id = etsy_listing_id(lock)
    if listing_id is None:
        raise EtsyListingNotMintedError(to)
    return listing_id
