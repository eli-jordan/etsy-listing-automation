"""Staging and batch endpoints (batch plan PR 2, 4 and 7; ADR-0048, ADR-0051, staging expiry):
stage one ZIP or loose PNGs against a listing template, review and edit the session,
cancel it or confirm it, then read the batch confirming made and steer its
AI queue -- cancel, resume, retry.

The operations are :mod:`etsy_listings.core.application.batch_staging`'s and
:mod:`~etsy_listings.core.application.batch_workflow`'s (module-structure
plan, PR 7). This module decodes the multipart upload into ``Upload``
streams, supplies the queue, the locks and AI readiness, and decides only
what each answer is on the wire:

* An upload refused before staging is a ``422`` whose ``detail`` is the
  sentence and the remedy (`StagingRefusal`), with nothing on disk.
* A session that cannot be confirmed yet is a ``409`` with the sentence, and
  nothing is created. So is one whose AI could not run (spec, *Design
  validation*), which the staging detail already says as ``ai_blocked``.
* An id nobody holds -- a session, a batch or a row -- is a ``404``. An id
  that is not a single path segment is the app-wide ``400``.

Both stores and the per-listing locks are the app's (`app.state`), so a
confirm and an editor's create of the same name wait for each other.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from etsy_listings.core.ai.proposals import ProposalStore
from etsy_listings.core.application import batch_staging, batch_workflow
from etsy_listings.core.application.batch_workflow import RecentBatch
from etsy_listings.core.application.refusals import (
    BatchMissing,
    BatchRowMissing,
    BatchRowNotReviewable,
    BatchRowUploadMissing,
    ListingTemplateMissing,
    NothingToRetry,
    StagedRowMissing,
    StagingMissing,
)
from etsy_listings.core.application.workspace_locks import WorkspaceLocks
from etsy_listings.core.batches import (
    Batch,
    BatchRow,
    BatchStore,
    ConfirmRefused,
    StagingRefused,
    StagingSession,
    StagingStore,
    Upload,
    review,
    reviewable,
    standing,
)
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.workspace.facts import WorkspaceFacts
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.airuns.registry import AiRunRegistry
from etsy_listings.server.api.schemas import (
    AiReadinessBlock,
    BatchDetail,
    BatchIndexEntry,
    BatchPatch,
    BatchRowDetail,
    ListingBatch,
    ReviewedRequest,
    StagingDetail,
    StagingPatch,
    StagingRefusal,
    StagingRowDetail,
    WorkflowStep,
)
from etsy_listings.server.api.seo import batch_readiness
from etsy_listings.server.api.thumbnails import thumbnail_response
from etsy_listings.server.batchqueue import BatchQueue

router = APIRouter(tags=["batches"])

_MISSING = (
    StagingMissing,
    StagedRowMissing,
    BatchMissing,
    BatchRowMissing,
    BatchRowUploadMissing,
    ListingTemplateMissing,
)
_CONFLICTS = (ConfirmRefused, NothingToRetry, BatchRowNotReviewable)


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


def _workspace(request: Request) -> Workspace:
    workspace: Workspace = request.app.state.workspace
    return workspace


def _staging(request: Request) -> StagingStore:
    store: StagingStore = request.app.state.staging_store
    return store


def _batches(request: Request) -> BatchStore:
    store: BatchStore = request.app.state.batch_store
    return store


def _locks(request: Request) -> WorkspaceLocks:
    locks: WorkspaceLocks = request.app.state.workspace_locks
    return locks


def _queue(request: Request) -> BatchQueue:
    queue: BatchQueue = request.app.state.batch_queue
    return queue


def _ai_blocked(request: Request) -> AiReadinessBlock | None:
    workspace = _workspace(request)
    return batch_readiness(
        workspace,
        request.app.state.seo_provider_factory(workspace),
        has_market=request.app.state.market_client_factory(workspace) is not None,
    )


def _staging_detail(request: Request, session: StagingSession) -> StagingDetail:
    workspace = _workspace(request)
    reviewed = review(workspace, session)
    return StagingDetail(
        ai_blocked=_ai_blocked(request),
        id=session.id,
        listing_template=session.listing_template,
        label=session.label,
        template_saved_at=session.template_saved_at,
        expires_at=session.expires_at,
        rows=[
            StagingRowDetail(
                id=row.id,
                sources=row.sources,
                name=row.name,
                typed=row.typed,
                state=row.state,
                message=row.message,
                note=row.note,
                suggestion=row.suggestion,
                reuse=row.reuse,
            )
            for row in reviewed.rows
        ],
        ignored=session.ignored,
    )


def _steps(request: Request, row: BatchRow) -> list[WorkflowStep]:
    """A running row's live run, else its last run as it ended."""
    if row.ai == "running":
        registry: AiRunRegistry = request.app.state.ai_run_registry
        run = registry.latest(row.name)
        if run is not None and run.origin == "batch" and not run.finished:
            return run.steps
    return [WorkflowStep.model_validate(step.model_dump()) for step in row.ai_steps]


def _batch_detail(request: Request, batch: Batch) -> BatchDetail:
    queue = _queue(request)
    positions = {slot: place for place, slot in enumerate(queue.order(), start=1)}
    workspace = _workspace(request)
    facts = WorkspaceFacts.gather(workspace)
    proposals: ProposalStore = request.app.state.proposal_store
    rows = []
    for row in batch.rows:
        proposal, stale = batch_workflow.row_proposal(workspace, proposals, row, facts=facts)
        rows.append(
            BatchRowDetail(
                id=row.id,
                sources=row.sources,
                name=row.name,
                design=row.design,
                creation=row.creation,
                error=row.error,
                ai=row.ai,
                ai_steps=_steps(request, row),
                ai_error=row.ai_error,
                queue_position=positions.get((batch.id, row.id)),
                proposal=proposal,
                stale_reasons=stale,
                reviewed=row.reviewed,
                reviewable=reviewable(row),
                deleted=row.deleted,
            )
        )
    return BatchDetail(
        id=batch.id,
        label=batch.label,
        listing_template=batch.listing_template,
        created_at=batch.created_at,
        rows=rows,
        concurrency=queue.concurrency(),
        status=standing(batch.rows).status,
    )


@router.post(
    "/api/staging",
    response_model=StagingDetail,
    responses={422: {"model": StagingRefusal}},
)
def create_staging(
    request: Request, listing_template: str = Form(...), files: list[UploadFile] | None = None
) -> StagingDetail:
    """Stage one ZIP or loose PNGs (spec, *Accepted input*). Starlette has
    already spooled the parts to temporary files; each is handed on as a
    stream, which staging reads a PNG or a ZIP's entries out of with a
    running count."""
    received = [Upload(filename=f.filename or "unnamed.png", stream=f.file) for f in files or []]
    try:
        session = batch_staging.stage_upload(
            _workspace(request),
            _staging(request),
            listing_template,
            received,
            locks=_locks(request),
        )
    except ListingTemplateMissing as exc:
        raise _not_found(exc) from exc
    except StagingRefused as exc:
        refusal = StagingRefusal(message=exc.message, remedy=exc.remedy)
        raise HTTPException(status_code=422, detail=refusal.model_dump()) from exc
    except ConfigLoadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _staging_detail(request, session)


@router.get("/api/staging/{session_id}", response_model=StagingDetail)
def get_staging(request: Request, session_id: str) -> StagingDetail:
    """A reload reattaches here (spec, *Frozen staging*)."""
    try:
        session = batch_staging.read_staging(_workspace(request), _staging(request), session_id)
    except StagingMissing as exc:
        raise _not_found(exc) from exc
    return _staging_detail(request, session)


@router.patch("/api/staging/{session_id}", response_model=StagingDetail)
def patch_staging(request: Request, session_id: str, body: StagingPatch) -> StagingDetail:
    """Edit the label, type names, remove rows. Every edit moves the
    session's expiry to seven days from now."""
    try:
        session = batch_staging.edit_staging(
            _workspace(request),
            _staging(request),
            session_id,
            label=body.label,
            names=body.names,
            remove=body.remove,
        )
    except _MISSING as exc:
        raise _not_found(exc) from exc
    return _staging_detail(request, session)


@router.delete("/api/staging/{session_id}", status_code=204)
def cancel_staging(request: Request, session_id: str) -> Response:
    """Cancel staging: the uploads go at once. The seller's own files
    were never touched."""
    try:
        batch_staging.cancel_staging(_workspace(request), _staging(request), session_id)
    except StagingMissing as exc:
        raise _not_found(exc) from exc
    return Response(status_code=204)


@router.get("/api/staging/{session_id}/rows/{row}/thumbnail")
def staging_row_thumbnail(request: Request, session_id: str, row: str) -> Response:
    try:
        path = batch_staging.staged_upload(_workspace(request), _staging(request), session_id, row)
    except _MISSING as exc:
        raise _not_found(exc) from exc
    return thumbnail_response(path)


@router.post(
    "/api/staging/{session_id}/confirm",
    response_model=BatchDetail,
    responses={409: {"description": "The session cannot be confirmed yet"}},
)
def confirm_staging(request: Request, session_id: str) -> BatchDetail:
    """Create N listings (UI doc §6). Repeating it -- a double click, a retry
    after a dropped response -- finishes the same batch rather than making a
    second one."""

    def ai_blocked() -> str | None:
        blocked = _ai_blocked(request)
        return blocked.message if blocked is not None else None

    try:
        batch = batch_workflow.confirm_batch(
            _workspace(request),
            _staging(request),
            _batches(request),
            session_id,
            locks=_locks(request),
            queue=_queue(request),
            ai_blocked=ai_blocked,
        )
    except StagingMissing as exc:
        raise _not_found(exc) from exc
    except ConfirmRefused as exc:
        raise _conflict(exc) from exc
    return _batch_detail(request, batch)


@router.get("/api/batches/{batch_id}", response_model=BatchDetail)
def get_batch(request: Request, batch_id: str) -> BatchDetail:
    try:
        batch = batch_workflow.read_batch(_workspace(request), _batches(request), batch_id)
    except BatchMissing as exc:
        raise _not_found(exc) from exc
    return _batch_detail(request, batch)


@router.post(
    "/api/batches/{batch_id}/rows/{row}/retry",
    response_model=BatchDetail,
    responses={409: {"description": "The row has nothing to retry"}},
)
def retry_batch_row(request: Request, batch_id: str, row: str) -> BatchDetail:
    """Retry one row (UI doc §7): its creation, if that failed -- which
    queues it once it exists -- else its AI, keeping the saved brief."""
    try:
        batch = batch_workflow.retry_batch_row(
            _workspace(request),
            _staging(request),
            _batches(request),
            batch_id,
            row,
            locks=_locks(request),
            queue=_queue(request),
        )
    except _MISSING as exc:
        raise _not_found(exc) from exc
    except _CONFLICTS as exc:
        raise _conflict(exc) from exc
    return _batch_detail(request, batch)


@router.post("/api/batches/{batch_id}/retry", response_model=BatchDetail)
def retry_batch(request: Request, batch_id: str) -> BatchDetail:
    """**Retry N failed**: every row whose creation or AI failed."""
    try:
        batch = batch_workflow.retry_batch(
            _workspace(request),
            _staging(request),
            _batches(request),
            batch_id,
            locks=_locks(request),
            queue=_queue(request),
        )
    except BatchMissing as exc:
        raise _not_found(exc) from exc
    return _batch_detail(request, batch)


@router.post("/api/batches/{batch_id}/cancel", response_model=BatchDetail)
def cancel_batch(request: Request, batch_id: str) -> BatchDetail:
    """**Cancel batch** (spec, *Cancellation and deletion*): queued rows are
    stopped and running ones asked to stop. Everything written stays."""
    try:
        batch = batch_workflow.cancel_batch(
            _workspace(request), _batches(request), batch_id, queue=_queue(request)
        )
    except BatchMissing as exc:
        raise _not_found(exc) from exc
    return _batch_detail(request, batch)


@router.post("/api/batches/{batch_id}/resume", response_model=BatchDetail)
def resume_batch(request: Request, batch_id: str) -> BatchDetail:
    """**Resume**: stopped and cancelled rows join the queue again."""
    try:
        batch = batch_workflow.resume_batch(
            _workspace(request), _batches(request), batch_id, queue=_queue(request)
        )
    except BatchMissing as exc:
        raise _not_found(exc) from exc
    return _batch_detail(request, batch)


# ------------------------------------------------ review and the batch index


@router.get("/api/batches", response_model=list[BatchIndexEntry])
def list_batches(request: Request) -> list[BatchIndexEntry]:
    """Recent batches (UI doc §2): every batch, and every staging session
    not confirmed yet, newest first, each with its derived status."""
    return [
        _index_entry(entry)
        for entry in batch_workflow.recent_batches(
            _workspace(request), _staging(request), _batches(request), now=datetime.now(UTC)
        )
    ]


def _index_entry(entry: RecentBatch) -> BatchIndexEntry:
    counts = entry.standing
    if counts is None:
        return BatchIndexEntry(
            kind="staging",
            id=entry.id,
            label=entry.label,
            listing_template=entry.listing_template,
            created_at=entry.created_at,
            status="staging",
            designs=entry.designs,
            expires_at=entry.expires_at,
        )
    return BatchIndexEntry(
        kind="batch",
        id=entry.id,
        label=entry.label,
        listing_template=entry.listing_template,
        created_at=entry.created_at,
        status=counts.status,
        designs=entry.designs,
        listings=counts.listings,
        drafted=counts.drafted,
        reviewed=counts.reviewed,
        undrafted=counts.undrafted,
        failures=counts.failures,
    )


@router.patch("/api/batches/{batch_id}", response_model=BatchDetail)
def rename_batch(request: Request, batch_id: str, body: BatchPatch) -> BatchDetail:
    """Rename the batch (UI doc §7): the label only, so its id -- and every
    link to it -- stays. A blank label keeps the one it had, as staging's
    does."""
    try:
        batch = batch_workflow.rename_batch(
            _workspace(request), _batches(request), batch_id, body.label
        )
    except BatchMissing as exc:
        raise _not_found(exc) from exc
    return _batch_detail(request, batch)


@router.delete("/api/batches/{batch_id}", status_code=204)
def delete_batch(request: Request, batch_id: str) -> Response:
    """Delete batch record (spec, *Cancellation and deletion*): its queued
    and running work is cancelled first, then only the record goes."""
    try:
        batch_workflow.delete_batch(
            _workspace(request), _batches(request), batch_id, queue=_queue(request)
        )
    except BatchMissing as exc:
        raise _not_found(exc) from exc
    return Response(status_code=204)


@router.put(
    "/api/batches/{batch_id}/rows/{row}/reviewed",
    response_model=BatchDetail,
    responses={409: {"description": "The row has no listing to review yet"}},
)
def set_reviewed(request: Request, batch_id: str, row: str, body: ReviewedRequest) -> BatchDetail:
    """Mark reviewed / Mark needs review (spec, *Review workflow*). Refused
    for a row still queued or drafting, deleted, or never created."""
    try:
        batch = batch_workflow.mark_reviewed(
            _workspace(request), _batches(request), batch_id, row, reviewed=body.reviewed
        )
    except _MISSING as exc:
        raise _not_found(exc) from exc
    except BatchRowNotReviewable as exc:
        raise _conflict(exc) from exc
    return _batch_detail(request, batch)


@router.get("/api/batches/{batch_id}/rows/{row}/thumbnail")
def batch_row_thumbnail(request: Request, batch_id: str, row: str) -> Response:
    """A row that was never created has no listing design to show, so the
    summary shows the upload it was made from, kept beside the batch for
    Retry."""
    try:
        path = batch_workflow.batch_row_upload(
            _workspace(request), _batches(request), batch_id, row
        )
    except _MISSING as exc:
        raise _not_found(exc) from exc
    return thumbnail_response(path)


@router.get("/api/listings/{name}/batch", response_model=ListingBatch | None)
def listing_batch(request: Request, name: str) -> ListingBatch | None:
    """The batch that made ``name``, for the editor's row above the head
    (UI doc §8), or ``null``."""
    found = batch_workflow.listing_batch(_workspace(request), _batches(request), name)
    if found is None:
        return None
    return ListingBatch(
        batch_id=found.batch.id,
        label=found.batch.label,
        row_id=found.row.id,
        reviewed=found.row.reviewed,
        reviewable=reviewable(found.row),
    )
