"""Batch creation: stage design PNGs against a listing template, then create
one ordinary local listing per design (spec *Starting a batch* to
*Confirming a batch*; ADR-0051).

Two cache records carry the work: a staging session, which is everything
uploaded but not yet confirmed, and a batch, which is what confirming made of
it. The stores are plain classes over `Workspace`; the UI server keeps one of
each. ``archive``'s ZIP checks are reached only through :func:`stage_pngs`.

Nothing here deploys or calls a provider. A created row is queued for AI
(``BatchRow.ai``), but the queue that drafts it is the UI server's
(``core/application/ai/batch_queue.py``, ADR-0048), since only that process
runs AI.
"""

from etsy_listings.core.batches.creation import (
    ConfirmRefusedError,
    confirm,
    retry_row,
    row_upload,
)
from etsy_listings.core.batches.naming import allocate
from etsy_listings.core.batches.records import (
    RETRYABLE,
    AiState,
    AiStep,
    Batch,
    BatchRecords,
    BatchRow,
    BatchStore,
    NotReviewableError,
    StagingRow,
    StagingSession,
    StagingStore,
    has_listing,
    reviewable,
)
from etsy_listings.core.batches.staging import (
    RowReview,
    StagingRefusedError,
    StagingReview,
    Upload,
    review,
    stage_pngs,
    upload_path,
)
from etsy_listings.core.batches.status import BatchStatus, Standing, standing

__all__ = [
    "RETRYABLE",
    "AiState",
    "AiStep",
    "Batch",
    "BatchRecords",
    "BatchRow",
    "BatchStatus",
    "BatchStore",
    "ConfirmRefusedError",
    "NotReviewableError",
    "RowReview",
    "StagingRefusedError",
    "StagingReview",
    "StagingRow",
    "StagingSession",
    "StagingStore",
    "Standing",
    "Upload",
    "allocate",
    "confirm",
    "has_listing",
    "retry_row",
    "review",
    "reviewable",
    "row_upload",
    "stage_pngs",
    "standing",
    "upload_path",
]
