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

from etsy_listings.core.batches import ConfirmRefused
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


# --------------------------------------------------------- listing templates
#
# ADR-0047, template completeness. A name already taken is the domain's own
# ``listing_templates.ListingTemplateExistsError``, for a create and a rename
# alike; a refused *document* is not raised but answered (``TemplateSave``).


class ListingTemplateMissing(UserFacingError, LookupError):
    """No ``listing-templates/{name}/template.yaml`` -- never was, or a rename
    or delete holding the template's lock moved it first."""

    def __init__(self, name: str) -> None:
        super().__init__(f"no listing template {name!r}")
        self.name = name


class ReservedListingTemplateName(UserFacingError, ValueError):
    """``draft`` names the *name it* page's unsaved template, so a listing
    template called that could be created and never opened."""

    def __init__(self, name: str) -> None:
        super().__init__(f"{name!r} is reserved; pick another name")
        self.name = name


class ListingTemplateSourceRefused(UserFacingError, ValueError):
    """What a new listing template is made from cannot become one: not
    exactly one source, a ``./`` file that cannot be read, a source document
    that will not load, or an edit naming a ``./`` file the template does
    not copy."""


# ------------------------------------------------------- staging and batches
#
# Batch creation's own refusals stay the domain's: ``batches.StagingRefused``
# for an upload refused before staging (ADR-0051's limits and archive
# safety), ``batches.ConfirmRefused`` for a session that cannot be confirmed
# yet. These are the ones the operations around them add.


class StagingMissing(UserFacingError, LookupError):
    """No staging session by this id: never staged, cancelled, confirmed and
    materialised, or swept seven days after its last edit."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"no staging session {session_id!r}")
        self.session_id = session_id


class StagedRowMissing(UserFacingError, LookupError):
    def __init__(self, row: str) -> None:
        super().__init__(f"no staged row {row!r}")
        self.row = row


class BatchMissing(UserFacingError, LookupError):
    def __init__(self, batch_id: str) -> None:
        super().__init__(f"no batch {batch_id!r}")
        self.batch_id = batch_id


class BatchRowMissing(UserFacingError, LookupError):
    def __init__(self, row: str) -> None:
        super().__init__(f"no batch row {row!r}")
        self.row = row


class BatchRowUploadMissing(UserFacingError, LookupError):
    """A never-created row whose upload is no longer kept anywhere."""

    def __init__(self, row: str) -> None:
        super().__init__(f"batch row {row!r} has no upload kept")
        self.row = row


class NothingToRetry(UserFacingError, ValueError):
    """The row was created and its AI is neither failed nor stopped -- or
    its listing was deleted, leaving nothing to draft."""

    def __init__(self, name: str) -> None:
        super().__init__(f"{name} has nothing to retry")
        self.name = name


class BatchRowNotReviewable(UserFacingError, ValueError):
    """Mark reviewed on a row still queued or drafting, deleted, or never
    created (spec, *Review workflow*)."""

    def __init__(self, name: str) -> None:
        super().__init__(f"{name} has no listing to review yet")
        self.name = name


class AiDraftingBlocked(ConfirmRefused):
    """Spec, *Design validation*: a batch is not knowingly created into a
    queue that cannot run. Nothing is created and the staging stays."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"AI drafting can't run yet. {reason}")
        self.reason = reason


class AiRunRefused(UserFacingError, ValueError):
    """An AI run may not start for this listing now; the message says why,
    in words the editor shows as AI Mode's hint. One of the three below."""

    def __init__(self, name: str, message: str) -> None:
        super().__init__(message)
        self.name = name


class ListingDeploying(AiRunRefused):
    """ADR-0050: a UI plan or apply holds the listing, and deploying takes
    precedence over AI. AI Mode is back once the deploy ends."""

    def __init__(self, name: str) -> None:
        super().__init__(
            name, "This listing is deploying. AI Mode is back once the deploy finishes."
        )


class ListingDraftingInBatch(AiRunRefused):
    """ADR-0048: a queued or running batch row owns the listing's AI, even
    while no run holds it yet -- two runs must never own one listing."""

    def __init__(self, name: str) -> None:
        super().__init__(
            name, "This listing is drafting in a batch. AI Mode is back once that is done."
        )


class AiNotReady(AiRunRefused):
    """A readiness rule failed (``ai/readiness.py``): the listing lacks a
    design, a brief or a usable garment profile, a prompt file is missing,
    or no provider is ready."""

    def __init__(self, name: str, reason: str) -> None:
        super().__init__(name, reason)
        self.reason = reason


class ProposalMissing(UserFacingError, LookupError):
    """No proposal is cached for the listing: none was generated, or a
    replacement, deletion, fully successful apply or cache clearing removed
    it (ADR-0049)."""

    def __init__(self, name: str) -> None:
        super().__init__(f"no proposal for {name!r}")
        self.name = name


class ProposalReplaced(UserFacingError, ValueError):
    """A resolution named a proposal regenerated since the page read it;
    nothing was recorded."""

    def __init__(self, name: str) -> None:
        super().__init__("this proposal was replaced by a newer one")
        self.name = name


class ReviewedPlanRefused(UserFacingError, ValueError):
    """ADR-0042: a workspace apply names exactly the listings and plan
    fingerprints of a ready workspace plan the seller reviewed, or it is not
    queued. The message says which part did not hold."""
