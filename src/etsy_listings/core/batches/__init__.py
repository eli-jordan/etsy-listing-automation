"""Batch creation: stage design PNGs against a listing template, then create
one ordinary local listing per design (spec *Starting a batch* to
*Confirming a batch*; cache-record persistence, ADR-0051, staging expiry; batch plan PR 2).

Two cache records carry the work (`records`): a staging session, which is
everything uploaded but not yet confirmed, and a batch, which is what
confirming made of it. The stores are plain classes over `Workspace`; the UI
server keeps one of each. Nothing here deploys, and nothing here calls a
provider.

* :func:`stage_pngs` -- the upload, one ZIP or loose PNGs, validated and
  frozen, or a :class:`StagingRefused` with nothing on disk. The ZIP's own
  checks are ``archive``'s, reached only through it.
* :func:`review` -- the names, checks and notes the staging page shows,
  worked out afresh on every read.
* :func:`confirm` and :func:`retry_row` -- create the listings, idempotently
.
* :func:`standing` -- a batch's derived status and progress counts, and
:func:`reviewable`, which rows Mark reviewed applies to (batch plan PR 5).

A created row is queued for AI (``BatchRow.ai``); the queue that drafts it
is the UI server's (``ui/batchqueue.py``, ADR-0048), since only that process runs
AI.
"""

from etsy_listings.batches.creation import ConfirmRefused, NameLock, confirm, retry_row, row_upload
from etsy_listings.batches.naming import allocate
from etsy_listings.batches.records import (
    AiState,
    AiStep,
    Batch,
    BatchRow,
    BatchStore,
    NotReviewable,
    StagingRow,
    StagingSession,
    StagingStore,
    has_listing,
    reviewable,
)
from etsy_listings.batches.staging import (
    RowReview,
    StagingRefused,
    StagingReview,
    Upload,
    review,
    stage_pngs,
    upload_path,
)
from etsy_listings.batches.status import BatchStatus, Standing, standing

__all__ = [
    # Records and their stores.
    "StagingSession",
    "StagingRow",
    "StagingStore",
    "Batch",
    "BatchRow",
    "AiState",
    "AiStep",
    "BatchStore",
    # Staging and its review.
    "Upload",
    "stage_pngs",
    "StagingRefused",
    "review",
    "StagingReview",
    "RowReview",
    "upload_path",
    "allocate",
    # Creating the listings.
    "confirm",
    "retry_row",
    "row_upload",
    "ConfirmRefused",
    "NameLock",
    # Where a batch stands (UI doc §2), and who may be reviewed (§7).
    "standing",
    "Standing",
    "BatchStatus",
    "reviewable",
    "has_listing",
    "NotReviewable",
]
