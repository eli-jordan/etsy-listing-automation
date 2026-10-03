"""A batch from confirm to review: creating its listings, the seller's
controls over its AI queue, its record, and the reads the batch pages and
the listing editor make of it (batch-creation spec, *Confirming a batch*
through *Review workflow*; ADR-0048; module-structure plan, PR 7).

Creating listings is ``batches``' -- ``confirm`` and ``retry_row`` allocate
each name under that listing's write lock and are idempotent, so a repeat
finishes the same batch rather than making a second. This module decides
around them: a new batch is not created into a queue that cannot run
(``BatchQueue.blocked``), Retry recreates a failed row or requeues its AI or
refuses, and every change that queues work wakes the queue. The queue is
:class:`~etsy_listings.core.application.ai.batch_queue.BatchQueue`, the one
the application runtime's AI coordinator dispatches from (ADR-0048).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from etsy_listings.core.ai.listing_inputs import ListingAiInputs
from etsy_listings.core.ai.proposals import ProposalStore
from etsy_listings.core.application.ai.batch_queue import BatchQueue
from etsy_listings.core.application.refusals import (
    AiDraftingBlocked,
    BatchMissing,
    BatchRowMissing,
    BatchRowNotReviewable,
    BatchRowUploadMissing,
    NothingToRetry,
    StagingMissing,
)
from etsy_listings.core.batches import (
    RETRYABLE,
    Batch,
    BatchRow,
    BatchStore,
    NotReviewable,
    StagingStore,
    Standing,
    confirm,
    has_listing,
    retry_row,
    row_upload,
    standing,
)
from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.workspace.facts import WorkspaceFacts
from etsy_listings.core.workspace.workspace import Workspace

ProposalState = Literal["ready", "stale", "resolved"]


# ------------------------------------------------------------- confirming


def confirm_batch(
    workspace: Workspace,
    staging: StagingStore,
    batches: BatchStore,
    session_id: str,
    *,
    queue: BatchQueue,
) -> Batch:
    """Create one listing per creatable row of staging session
    ``session_id`` -- or finish the batch a previous confirm began -- and
    wake the queue for the rows now queued.

    Only a *new* batch asks whether the queue could draft: one that exists
    already has listings half made, and is finished whatever AI's state.
    Refusals, with nothing created: :class:`AiDraftingBlocked`,
    ``batches.ConfirmRefused`` (names to fix, nothing creatable, a shared ref
    broken since staging), :class:`StagingMissing`, ``InvalidNameError``.
    """
    workspace.staging_dir(session_id)
    if batches.load(session_id) is None:
        blocked = queue.blocked()
        if blocked is not None:
            raise AiDraftingBlocked(blocked.message)
    try:
        batch = confirm(workspace, staging, batches, session_id)
    except KeyError as exc:
        raise StagingMissing(session_id) from exc
    queue.wake()
    return batch


# --------------------------------------------------------------- retrying


def retry_batch_row(
    workspace: Workspace,
    staging: StagingStore,
    batches: BatchStore,
    batch_id: str,
    row_id: str,
    *,
    queue: BatchQueue,
) -> Batch:
    """Retry one row (UI doc §7): its creation, if that failed -- which
    queues it once it exists -- else its AI, keeping the saved brief.
    :class:`NothingToRetry` for a row whose AI is not failed, stopped or
    cancelled, or whose listing was deleted."""
    batch = read_batch(workspace, batches, batch_id)
    target = _row(batch, row_id)
    if target.creation == "failed":
        _recreate(workspace, staging, batches, batch_id, {row_id}, queue=queue)
    elif target.ai in RETRYABLE and not target.deleted:
        queue.retry(batch_id, row_id)
    else:
        raise NothingToRetry(target.name)
    return read_batch(workspace, batches, batch_id)


def retry_batch(
    workspace: Workspace,
    staging: StagingStore,
    batches: BatchStore,
    batch_id: str,
    *,
    queue: BatchQueue,
) -> Batch:
    """**Retry N failed**: every row whose creation failed is created, then
    every row whose AI failed is queued again."""
    batch = read_batch(workspace, batches, batch_id)
    failed = {row.id for row in batch.rows if row.creation == "failed"}
    _recreate(workspace, staging, batches, batch_id, failed, queue=queue)
    queue.retry(batch_id)
    return read_batch(workspace, batches, batch_id)


def _recreate(
    workspace: Workspace,
    staging: StagingStore,
    batches: BatchStore,
    batch_id: str,
    rows: Iterable[str],
    *,
    queue: BatchQueue,
) -> None:
    for row in rows:
        retry_row(workspace, staging, batches, batch_id, row)
    queue.wake()


# --------------------------------------------- steering and the record


def cancel_batch(
    workspace: Workspace, batches: BatchStore, batch_id: str, *, queue: BatchQueue
) -> Batch:
    """**Cancel batch** (spec, *Cancellation and deletion*): queued rows are
    stopped and running ones asked to stop. Everything written stays."""
    read_batch(workspace, batches, batch_id)
    queue.cancel(batch_id)
    return read_batch(workspace, batches, batch_id)


def resume_batch(
    workspace: Workspace, batches: BatchStore, batch_id: str, *, queue: BatchQueue
) -> Batch:
    """**Resume**: stopped and cancelled rows join the queue again."""
    read_batch(workspace, batches, batch_id)
    queue.resume(batch_id)
    return read_batch(workspace, batches, batch_id)


def delete_batch(
    workspace: Workspace, batches: BatchStore, batch_id: str, *, queue: BatchQueue
) -> None:
    """Delete the batch record (spec, *Cancellation and deletion*): its
    queued and running work is cancelled first, then only the record goes --
    rows, review flags, queue state and its frozen template. Designs,
    listings, briefs and proposals are the workspace's and stay."""
    read_batch(workspace, batches, batch_id)
    queue.cancel(batch_id)
    with batches.lock(batch_id):
        batches.remove(batch_id)
    queue.wake()


def rename_batch(workspace: Workspace, batches: BatchStore, batch_id: str, label: str) -> Batch:
    """The label only, so its id -- and every link to it -- stays. A blank
    label keeps the one it had."""
    with batches.lock(batch_id):
        batch = read_batch(workspace, batches, batch_id)
        label = label.strip()
        if label and label != batch.label:
            batch = batch.model_copy(update={"label": label})
            batches.save(batch)
    return batch


def mark_reviewed(
    workspace: Workspace, batches: BatchStore, batch_id: str, row_id: str, *, reviewed: bool
) -> Batch:
    """Mark reviewed / Mark needs review (spec, *Review workflow*).
    :class:`BatchRowNotReviewable` for a row still queued or drafting,
    deleted, or never created."""
    read_batch(workspace, batches, batch_id)
    try:
        return batches.review(batch_id, row_id, reviewed=reviewed)
    except KeyError as exc:
        raise BatchRowMissing(row_id) from exc
    except NotReviewable as exc:
        raise BatchRowNotReviewable(exc.args[0]) from exc


# ------------------------------------------------------------------ reads


def read_batch(workspace: Workspace, batches: BatchStore, batch_id: str) -> Batch:
    """``InvalidNameError`` for an id that is not a path segment;
    :class:`BatchMissing` for one nobody holds."""
    workspace.batch_file(batch_id)
    batch = batches.load(batch_id)
    if batch is None:
        raise BatchMissing(batch_id)
    return batch


def batch_row_upload(workspace: Workspace, batches: BatchStore, batch_id: str, row_id: str) -> Path:
    """The upload a row was made from: what a row that was never created
    shows on the summary, having no listing design. Kept beside the batch
    for Retry once the staging session has gone."""
    batch = read_batch(workspace, batches, batch_id)
    try:
        path = row_upload(workspace, batch, row_id)
    except KeyError as exc:
        raise BatchRowMissing(row_id) from exc
    if not path.is_file():
        raise BatchRowUploadMissing(row_id)
    return path


@dataclass(frozen=True)
class ListingMembership:
    batch: Batch
    row: BatchRow


def listing_batch(workspace: Workspace, batches: BatchStore, name: str) -> ListingMembership | None:
    """The batch that made listing ``name``, for the editor's row above the
    head (UI doc §8), or ``None``. A row names its listing exactly, as the
    rename and delete hooks match it; a deleted row is not the listing's.
    Should two batches both claim it, the newer wins."""
    workspace.listing_dir(name)
    newest = sorted(batches.all(), key=lambda b: (b.created_at, b.id), reverse=True)
    for batch in newest:
        for row in batch.rows:
            if row.name == name and has_listing(row):
                return ListingMembership(batch=batch, row=row)
    return None


@dataclass(frozen=True)
class RecentBatch:
    """One row of Recent batches (UI doc §2): a confirmed batch, with where
    it stands, or a staging session not confirmed yet (``standing`` ``None``),
    which reopens staging and expires."""

    kind: Literal["staging", "batch"]
    id: str
    label: str
    listing_template: str
    created_at: datetime
    designs: int
    standing: Standing | None = None
    expires_at: datetime | None = None


def recent_batches(
    workspace: Workspace,
    staging: StagingStore,
    batches: BatchStore,
    *,
    now: datetime | None = None,
) -> list[RecentBatch]:
    """Every batch, and every staging session not confirmed yet, newest
    first. Expired staging is swept first, so the list never offers a
    session that has gone. A confirmed session stays until every row is
    materialised and shares its batch's id: that one is listed as the
    batch."""
    staging.sweep(now=now or datetime.now(UTC))
    recorded = batches.all()
    confirmed = {batch.id for batch in recorded}
    entries = [
        RecentBatch(
            kind="batch",
            id=batch.id,
            label=batch.label,
            listing_template=batch.listing_template,
            created_at=batch.created_at,
            designs=len(batch.rows),
            standing=standing(batch.rows),
        )
        for batch in recorded
    ]
    for session_id in workspace.staging_ids():
        session = staging.load(session_id) if session_id not in confirmed else None
        if session is not None:
            entries.append(
                RecentBatch(
                    kind="staging",
                    id=session.id,
                    label=session.label,
                    listing_template=session.listing_template,
                    created_at=session.created_at,
                    designs=len(session.rows),
                    expires_at=session.expires_at,
                )
            )
    return sorted(entries, key=lambda entry: (entry.created_at, entry.id), reverse=True)


def row_proposal(
    workspace: Workspace, proposals: ProposalStore, row: BatchRow, *, facts: WorkspaceFacts
) -> tuple[ProposalState | None, list[str]]:
    """The row's listing's cached proposal, judged as the editor judges it
    (ADR-0049), so the summary's *Stale: ...* is the drawer's: sections
    waiting and current, waiting but out of date (with why), or every
    section dealt with. ``None`` without a listing or a proposal, or when
    the listing will not read."""
    record = proposals.load(row.name) if has_listing(row) else None
    if record is None:
        return None, []
    try:
        judged = ListingAiInputs.read(workspace, row.name, facts=facts).judge(record)
    except (UserFacingError, OSError, ValidationError):
        return None, []
    if all(state != "pending" for state in judged.resolution.model_dump().values()):
        return "resolved", []
    if judged.stale.is_stale:
        return "stale", judged.stale.reasons
    return "ready", []


def _row(batch: Batch, row_id: str) -> BatchRow:
    row = next((r for r in batch.rows if r.id == row_id), None)
    if row is None:
        raise BatchRowMissing(row_id)
    return row
