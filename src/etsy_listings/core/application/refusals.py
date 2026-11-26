"""Two shapes, because there are two kinds of "no". A refusal that ends the
operation is raised: nothing was written, and the caller has nothing else to
report. A malformed document is *returned*, because the caller still has a
listing (or an empty draft) to describe alongside it: invalid input is a 200
with the listing unchanged. Incompleteness is neither: ADR-0043 writes an
incomplete listing and leaves its gaps to ``config/listing_validation.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from etsy_listings.core.batches import ConfirmRefusedError
from etsy_listings.core.config.listing_validation import DELETED_ON_PUBLISHED
from etsy_listings.core.errors import (
    ConflictError,
    MissingError,
    RefusedError,
    StaleError,
    UserFacingError,
)
from etsy_listings.core.workspace.listing_documents import (
    ListingMissingError as ListingMissingError,
)
from etsy_listings.core.workspace.listing_documents import (
    ListingNameTakenError as ListingNameTakenError,
)
from etsy_listings.core.workspace.workspace import InvalidNameError


class PublishedListingDeletionError(ConflictError, ValueError):
    """ADR-0035."""

    def __init__(self, name: str) -> None:
        super().__init__(DELETED_ON_PUBLISHED)
        self.name = name


@dataclass(frozen=True)
class InvalidListing:
    field_errors: dict[str, str]

    @classmethod
    def of(cls, exc: ValidationError) -> InvalidListing:
        return cls(field_errors_of(exc))


def field_errors_of(exc: ValidationError) -> dict[str, str]:
    result: dict[str, str] = {}
    for error in exc.errors():
        loc = ".".join(str(part) for part in error["loc"]) or "__root__"
        result[loc] = error["msg"]
    return result


class TemplateMissingError(MissingError):
    def __init__(self, name: str) -> None:
        super().__init__(f"no template {name!r}")
        self.name = name


class TemplateAlreadyCalibratedError(ConflictError, ValueError):
    def __init__(self, name: str) -> None:
        super().__init__(f"{name!r} already has a template.yaml; delete it to change kind")
        self.name = name


class TemplateNameTakenError(ConflictError, ValueError):
    """On Windows a name differing only in case is the same directory, so it is taken."""

    def __init__(self, name: str) -> None:
        super().__init__(f"a template already exists named {name!r}")
        self.name = name


class TemplateInUseError(ConflictError): ...


class TemplateKindRefusedError(RefusedError): ...


class TemplatePreviewKindMismatchError(RefusedError):
    def __init__(self, kind: str) -> None:
        super().__init__(f"expected a {kind} preview body")
        self.kind = kind


class TemplatePhotoMissingError(MissingError): ...


class DesignUploadRefusedError(RefusedError): ...


class ListingDesignUploadRefusedError(RefusedError): ...


class CalibrationDesignMissingError(MissingError):
    def __init__(self, design: str) -> None:
        super().__init__(f"unknown test design {design!r}")
        self.design = design


# --------------------------------------------------------- listing templates
# A taken name is ``listing_templates.ListingTemplateExistsError``.


class ListingTemplateMissingError(MissingError):
    def __init__(self, name: str) -> None:
        super().__init__(f"no listing template {name!r}")
        self.name = name


class ReservedListingTemplateNameError(UserFacingError, InvalidNameError):
    def __init__(self, name: str) -> None:
        super().__init__(name, f"{name!r} is reserved; pick another name")
        self.name = name


class ListingTemplateSourceRefusedError(RefusedError): ...


# ------------------------------------------------------- staging and batches
# ``batches.StagingRefusedError`` and ``ConfirmRefusedError`` stay in ``batches``.


class StagingMissingError(MissingError):
    """No staging session by this id: never staged, cancelled, confirmed and
    materialised, or swept
    :data:`~etsy_listings.core.batches.records.STAGING_LIFETIME` after its
    last edit."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"no staging session {session_id!r}")
        self.session_id = session_id


class StagedRowMissingError(MissingError):
    def __init__(self, row: str) -> None:
        super().__init__(f"no staged row {row!r}")
        self.row = row


class BatchMissingError(MissingError):
    def __init__(self, batch_id: str) -> None:
        super().__init__(f"no batch {batch_id!r}")
        self.batch_id = batch_id


class BatchRowMissingError(MissingError):
    def __init__(self, row: str) -> None:
        super().__init__(f"no batch row {row!r}")
        self.row = row


class BatchRowUploadMissingError(MissingError):
    def __init__(self, row: str) -> None:
        super().__init__(f"batch row {row!r} has no upload kept")
        self.row = row


class NothingToRetryError(ConflictError, ValueError):
    def __init__(self, name: str) -> None:
        super().__init__(f"{name} has nothing to retry")
        self.name = name


class BatchRowNotReviewableError(ConflictError, ValueError):
    def __init__(self, name: str) -> None:
        super().__init__(f"{name} has no listing to review yet")
        self.name = name


class NothingToDeployError(ConflictError, ValueError):
    """ADR-0059."""

    def __init__(self, label: str) -> None:
        super().__init__(f"{label} has no reviewed listings with changes to deploy")
        self.label = label


class AiDraftingBlockedError(ConfirmRefusedError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"AI drafting can't run yet. {reason}")
        self.reason = reason


class AiRunRefusedError(ConflictError, ValueError):
    """The message is shown as AI Mode's hint."""

    def __init__(self, name: str, message: str) -> None:
        super().__init__(message)
        self.name = name


class ListingDeployingError(AiRunRefusedError):
    """ADR-0050."""

    def __init__(self, name: str) -> None:
        super().__init__(
            name, "This listing is deploying. AI Mode is back once the deploy finishes."
        )


class ListingDraftingInBatchError(AiRunRefusedError):
    """ADR-0048."""

    def __init__(self, name: str) -> None:
        super().__init__(
            name, "This listing is drafting in a batch. AI Mode is back once that is done."
        )


class AiNotReadyError(AiRunRefusedError):
    def __init__(self, name: str, reason: str) -> None:
        super().__init__(name, reason)
        self.reason = reason


class ProposalMissingError(MissingError):
    """ADR-0049."""

    def __init__(self, name: str) -> None:
        super().__init__(f"no proposal for {name!r}")
        self.name = name


class ProposalReplacedError(StaleError, ValueError):
    def __init__(self, name: str) -> None:
        super().__init__("this proposal was replaced by a newer one")
        self.name = name


class ReviewedPlanRefusedError(ConflictError, ValueError):
    """ADR-0042."""


class ShopRevisionConflictError(StaleError, RuntimeError):
    def __init__(self) -> None:
        super().__init__("shop.yaml changed on disk since this page loaded it. Reload to continue.")


class InvalidShopEditError(RefusedError):
    def __init__(self, field_errors: dict[str, str]) -> None:
        super().__init__("; ".join(f"{key}: {message}" for key, message in field_errors.items()))
        self.field_errors = field_errors


class SettingsRevisionConflictError(StaleError, RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "settings.yaml changed on disk since this page loaded it. Reload to continue."
        )


class InvalidSettingsEditError(RefusedError):
    def __init__(self, field_errors: dict[str, str]) -> None:
        super().__init__("; ".join(f"{key}: {message}" for key, message in field_errors.items()))
        self.field_errors = field_errors
