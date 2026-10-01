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


# ---------------------------------------------------------- mockup templates
#
# The calibrator's (module-structure plan, PR 7). A mockup template is a
# folder of photos the seller put in the workspace; nothing creates one, so
# every operation names one that must already exist.


class TemplateMissing(UserFacingError, LookupError):
    """No ``mockup-templates/{name}/`` directory."""

    def __init__(self, name: str) -> None:
        super().__init__(f"no template {name!r}")
        self.name = name


class TemplateConfigMissing(UserFacingError, LookupError):
    """The template has no ``template.yaml`` -- the normal state of a folder
    nobody has given a kind yet: absent, not broken."""

    def __init__(self, name: str) -> None:
        super().__init__(f"no template.yaml for {name!r}")
        self.name = name


class TemplateAlreadyCalibrated(UserFacingError, ValueError):
    """Kind decides the whole ``template.yaml`` shape, so assigning another
    would silently discard the calibration done in the old one's fields."""

    def __init__(self, name: str) -> None:
        super().__init__(f"{name!r} already has a template.yaml; delete it to change kind")
        self.name = name


class TemplateKindRefused(UserFacingError, ValueError):
    """The folder's photos cannot be the kind asked for: none at all, or a
    set where a fixed scene takes exactly one."""


class TemplatePreviewKindMismatch(UserFacingError, ValueError):
    """Unsaved preview geometry shaped for another kind than the template
    is -- a well-formed request that is wrong for this template."""

    def __init__(self, kind: str) -> None:
        super().__init__(f"expected a {kind} preview body")
        self.kind = kind


class TemplatePhotoMissing(UserFacingError, LookupError):
    """There is no one photo to show, sample or composite over: none for the
    colour asked about, an ambiguous colour suffix, or a template kind that
    has no per-colour photos at all. The message names what was asked for."""
