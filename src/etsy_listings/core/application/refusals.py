"""What a listing operation answers instead of doing what it was asked.

Application meaning only, no status codes (module-structure spec,
*Responsibility and dependency rules*): an adapter decides what each becomes
-- the listings API turns :class:`ListingMissing` into a 404 and the name and
publication refusals into 409s, while :class:`InvalidListing` stays an
ordinary answer carrying field errors (``ListingDetail.field_errors``).

Two shapes, because there are two kinds of "no". A refusal that ends the
operation is raised: nothing was written, and the caller has nothing else to
report. A malformed document is *returned*, because the caller still has a
listing (or an empty draft) to describe alongside it -- the contract the
editor has always relied on, where invalid input is a 200 with the listing
unchanged. Incompleteness is neither: ADR-0043 writes an incomplete listing
and leaves its gaps to ``config/listing_validation.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from etsy_listings.core.config.listing_validation import DELETED_ON_PUBLISHED
from etsy_listings.core.errors import UserFacingError


class ListingMissing(UserFacingError, LookupError):
    """There is no ``listing.yaml`` by this name -- never was, or a rename
    or delete holding the listing's lock moved it first."""

    def __init__(self, name: str) -> None:
        super().__init__(f"no listing {name!r}")
        self.name = name


class ListingNameTaken(UserFacingError, ValueError):
    """A create or rename named a listing directory that already exists --
    with or without a ``listing.yaml`` in it, since a lockfile left behind
    would hand its remote ids to the newcomer."""

    def __init__(self, name: str) -> None:
        super().__init__(f"a listing already exists named {name!r}")
        self.name = name


class PublishedListingDeletion(UserFacingError, ValueError):
    """ADR-0035: a listing Etsy has published is retired, never deleted."""

    def __init__(self, name: str) -> None:
        super().__init__(DELETED_ON_PUBLISHED)
        self.name = name


@dataclass(frozen=True)
class InvalidListing:
    """A candidate document that does not structurally validate as a
    ``Listing``: each failed field, dotted, to pydantic's message. Nothing was
    written."""

    field_errors: dict[str, str]

    @classmethod
    def of(cls, exc: ValidationError) -> InvalidListing:
        return cls(field_errors_of(exc))


def field_errors_of(exc: ValidationError) -> dict[str, str]:
    """Each failed field, dotted, to pydantic's message -- for a listing, and
    for a listing template's refused save."""
    result: dict[str, str] = {}
    for error in exc.errors():
        loc = ".".join(str(part) for part in error["loc"]) or "__root__"
        result[loc] = error["msg"]
    return result
