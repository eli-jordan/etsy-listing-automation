"""Staging and batch endpoints (batch plan PR 2, 4 and 7; ADR-0048, ADR-0051, staging expiry):
stage one ZIP or loose PNGs against a listing template, review and edit the session,
cancel it or confirm it, then read the batch confirming made and steer its
AI queue -- cancel, resume, retry.

The operations are :mod:`etsy_listings.core.application.batch_staging`'s and
:mod:`~etsy_listings.core.application.batch_workflow`'s (module-structure
plan, PR 7). This module decodes the multipart upload into ``Upload``
streams and supplies the AI coordinator's batch queue (which also says
whether AI could run). The refusals reach the wire through the app's one
refusal table (``app.py``'s ``REFUSAL_STATUS``):

* An upload refused before staging is a ``422`` whose ``detail`` is the
  sentence and the remedy (`StagingRefusal`), with nothing on disk -- the one
  refusal this module answers itself, for its body.
* A session that cannot be confirmed yet is a ``409`` with the sentence, and
  nothing is created. So is one whose AI could not run (spec, *Design
  validation*), which the staging detail already says as ``ai_blocked``.
* An id nobody holds -- a session, a batch or a row -- is a ``404``. An id
  that is not a single path segment is a ``400``.

Both stores are the app's (`app.state`). A confirm and an editor's create of
the same name wait for each other on the listing's document lock
(``core/workspace/listing_documents.py``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from etsy_listings.core.ai.proposals import ProposalStore
from etsy_listings.core.application import batch_staging, batch_workflow
from etsy_listings.core.application.ai.batch_queue import BatchQueue
from etsy_listings.core.application.ai.registry import AiRunRegistry
from etsy_listings.core.application.batch_workflow import RecentBatch
from etsy_listings.core.batches import (
    Batch,
    BatchRecords,
    BatchRow,
    StagingRefusedError,
    StagingSession,
    Upload,
    review,
    reviewable,
    standing,
)
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.workspace.facts import WorkspaceFacts
from etsy_listings.server.api import app_state
from etsy_listings.server.api.schemas import (
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
from etsy_listings.server.api.thumbnails import thumbnail_response

router = APIRouter(tags=["batches"])


def _queue(request: Request) -> BatchQueue:
    queue: BatchQueue = request.app.state.ai.queue
    return queue


def _staging_detail(request: Request, session: StagingSession) -> StagingDetail:
    workspace = app_state.workspace(request)
    reviewed = review(workspace, session)
    return StagingDetail(
        ai_blocked=_queue(request).blocked(),
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
        registry: AiRunRegistry = request.app.state.ai.registry
        run = registry.latest(row.name)
        if run is not None and run.origin == "batch" and not run.finished:
            return run.steps
    return [WorkflowStep.model_validate(step.model_dump()) for step in row.ai_steps]


def _batch_detail(request: Request, batch: Batch) -> BatchDetail:
    queue = _queue(request)
    try:
        concurrency = queue.concurrency()
    except ConfigLoadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    positions = {slot: place for place, slot in enumerate(queue.order(), start=1)}
    workspace = app_state.workspace(request)
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
        concurrency=concurrency,
        status=standing(batch.rows).status,
    )


@router.post(
    "/api/staging",
    response_model=StagingDetail,
    responses={422: {"model": StagingRefusal}},
)
def create_staging(
    request: Request,
    listing_template: Annotated[str, Form()],
    files: list[UploadFile] | None = None,
) -> StagingDetail:
    """Stage one ZIP or loose PNGs (spec, *Accepted input*). Starlette has
    already spooled the parts to temporary files; each is handed on as a
    stream, which staging reads a PNG or a ZIP's entries out of with a
    running count."""
    received = [Upload(filename=f.filename or "unnamed.png", stream=f.file) for f in files or []]
    try:
        session = batch_staging.stage_upload(
            app_state.staging_store(request),
            listing_template,
            received,
        )
    except StagingRefusedError as exc:
        refusal = StagingRefusal(message=exc.message, remedy=exc.remedy)
        raise HTTPException(status_code=422, detail=refusal.model_dump()) from exc
    except ConfigLoadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _staging_detail(request, session)


@router.get("/api/staging/{session_id}", response_model=StagingDetail)
def get_staging(request: Request, session_id: str) -> StagingDetail:
    """A reload reattaches here (spec, *Frozen staging*)."""
    session = batch_staging.read_staging(
        app_state.workspace(request), app_state.staging_store(request), session_id
    )
    return _staging_detail(request, session)


@router.patch("/api/staging/{session_id}", response_model=StagingDetail)
def patch_staging(request: Request, session_id: str, body: StagingPatch) -> StagingDetail:
    """Edit the label, type names, remove rows. Every edit moves the
    session's expiry to seven days from now."""
    session = batch_staging.edit_staging(
        app_state.workspace(request),
        app_state.staging_store(request),
        session_id,
        batch_staging.StagingEdit(label=body.label, names=body.names, remove=body.remove),
    )
    return _staging_detail(request, session)


@router.delete("/api/staging/{session_id}", status_code=204)
def cancel_staging(request: Request, session_id: str) -> Response:
    """Cancel staging: the uploads go at once. The seller's own files
    were never touched."""
    batch_staging.cancel_staging(
        app_state.workspace(request), app_state.staging_store(request), session_id
    )
    return Response(status_code=204)


@router.get("/api/staging/{session_id}/rows/{row}/thumbnail")
def staging_row_thumbnail(request: Request, session_id: str, row: str) -> Response:
    path = batch_staging.staged_upload(
        app_state.workspace(request), app_state.staging_store(request), session_id, row
    )
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
    batch = batch_workflow.confirm_batch(
        app_state.workspace(request),
        BatchRecords(app_state.staging_store(request), app_state.batch_store(request)),
        session_id,
        queue=_queue(request),
    )
    return _batch_detail(request, batch)


@router.get("/api/batches/{batch_id}", response_model=BatchDetail)
def get_batch(request: Request, batch_id: str) -> BatchDetail:
    batch = batch_workflow.read_batch(
        app_state.workspace(request), app_state.batch_store(request), batch_id
    )
    return _batch_detail(request, batch)


@router.post(
    "/api/batches/{batch_id}/rows/{row}/retry",
    response_model=BatchDetail,
    responses={409: {"description": "The row has nothing to retry"}},
)
def retry_batch_row(request: Request, batch_id: str, row: str) -> BatchDetail:
    """Retry one row (UI doc §7): its creation, if that failed -- which
    queues it once it exists -- else its AI, keeping the saved brief."""
    batch = batch_workflow.retry_batch_row(
        app_state.workspace(request),
        BatchRecords(app_state.staging_store(request), app_state.batch_store(request)),
        batch_id,
        row,
        queue=_queue(request),
    )
    return _batch_detail(request, batch)


@router.post("/api/batches/{batch_id}/retry", response_model=BatchDetail)
def retry_batch(request: Request, batch_id: str) -> BatchDetail:
    """**Retry N failed**: every row whose creation or AI failed."""
    batch = batch_workflow.retry_batch(
        app_state.workspace(request),
        BatchRecords(app_state.staging_store(request), app_state.batch_store(request)),
        batch_id,
        queue=_queue(request),
    )
    return _batch_detail(request, batch)


@router.post("/api/batches/{batch_id}/cancel", response_model=BatchDetail)
def cancel_batch(request: Request, batch_id: str) -> BatchDetail:
    """**Cancel batch** (spec, *Cancellation and deletion*): queued rows are
    stopped and running ones asked to stop. Everything written stays."""
    batch = batch_workflow.cancel_batch(
        app_state.workspace(request),
        app_state.batch_store(request),
        batch_id,
        queue=_queue(request),
    )
    return _batch_detail(request, batch)


@router.post("/api/batches/{batch_id}/resume", response_model=BatchDetail)
def resume_batch(request: Request, batch_id: str) -> BatchDetail:
    """**Resume**: stopped and cancelled rows join the queue again."""
    batch = batch_workflow.resume_batch(
        app_state.workspace(request),
        app_state.batch_store(request),
        batch_id,
        queue=_queue(request),
    )
    return _batch_detail(request, batch)


# ------------------------------------------------ review and the batch index


@router.get("/api/batches", response_model=list[BatchIndexEntry])
def list_batches(request: Request) -> list[BatchIndexEntry]:
    """Recent batches (UI doc §2): every batch, and every staging session
    not confirmed yet, newest first, each with its derived status."""
    return [
        _index_entry(entry)
        for entry in batch_workflow.recent_batches(
            app_state.workspace(request),
            app_state.staging_store(request),
            app_state.batch_store(request),
            now=datetime.now(UTC),
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
    batch = batch_workflow.rename_batch(
        app_state.workspace(request), app_state.batch_store(request), batch_id, body.label
    )
    return _batch_detail(request, batch)


@router.delete("/api/batches/{batch_id}", status_code=204)
def delete_batch(request: Request, batch_id: str) -> Response:
    """Delete batch record (spec, *Cancellation and deletion*): its queued
    and running work is cancelled first, then only the record goes."""
    batch_workflow.delete_batch(
        app_state.workspace(request),
        app_state.batch_store(request),
        batch_id,
        queue=_queue(request),
    )
    return Response(status_code=204)


@router.put(
    "/api/batches/{batch_id}/rows/{row}/reviewed",
    response_model=BatchDetail,
    responses={409: {"description": "The row has no listing to review yet"}},
)
def set_reviewed(request: Request, batch_id: str, row: str, body: ReviewedRequest) -> BatchDetail:
    """Mark reviewed / Mark needs review (spec, *Review workflow*). Refused
    for a row still queued or drafting, deleted, or never created."""
    batch = batch_workflow.mark_reviewed(
        app_state.workspace(request),
        app_state.batch_store(request),
        batch_id,
        row,
        reviewed=body.reviewed,
    )
    return _batch_detail(request, batch)


@router.get("/api/batches/{batch_id}/rows/{row}/thumbnail")
def batch_row_thumbnail(request: Request, batch_id: str, row: str) -> Response:
    """A row that was never created has no listing design to show, so the
    summary shows the upload it was made from, kept beside the batch for
    Retry."""
    path = batch_workflow.batch_row_upload(
        app_state.workspace(request), app_state.batch_store(request), batch_id, row
    )
    return thumbnail_response(path)


@router.get("/api/listings/{name}/batch", response_model=ListingBatch | None)
def listing_batch(request: Request, name: str) -> ListingBatch | None:
    """The batch that made ``name``, for the editor's row above the head
    (UI doc §8), or ``null``."""
    found = batch_workflow.listing_batch(
        app_state.workspace(request), app_state.batch_store(request), name
    )
    if found is None:
        return None
    return ListingBatch(
        batch_id=found.batch.id,
        label=found.batch.label,
        row_id=found.row.id,
        reviewed=found.row.reviewed,
        reviewable=reviewable(found.row),
    )
