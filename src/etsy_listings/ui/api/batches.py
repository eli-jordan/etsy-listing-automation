"""Staging and batch endpoints (batch plan PR 2, 4 and 7; A37-A40, A45, A46):
stage one ZIP or loose PNGs against a listing template, review and edit the session,
cancel it or confirm it, then read the batch confirming made and steer its
AI queue -- cancel, resume, retry.

The rules are `batches`'; this module decides only what each answer is on
the wire:

* An upload refused before staging is a ``422`` whose ``detail`` is the
  sentence and the remedy (`StagingRefusal`), with nothing on disk.
* A session that cannot be confirmed yet is a ``409`` with the sentence, and
  nothing is created. So is one whose AI could not run (spec, *Design
  validation*), which the staging detail already says as ``ai_blocked``.
* An id nobody holds -- a session, a batch or a row -- is a ``404``. An id
  that is not a single path segment is the app-wide ``400``.

Both stores and the per-listing locks are the app's (`app.state`), so a
confirm and an editor's create of the same name wait for each other (A38).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import ValidationError

from etsy_listings.ai.proposals import ProposalStore
from etsy_listings.batches import (
    Batch,
    BatchRow,
    BatchStore,
    ConfirmRefused,
    NotReviewable,
    StagingRefused,
    StagingSession,
    StagingStore,
    Upload,
    confirm,
    has_listing,
    retry_row,
    review,
    reviewable,
    row_upload,
    stage_pngs,
    standing,
    upload_path,
)
from etsy_listings.config.errors import ConfigLoadError
from etsy_listings.ui.airuns.registry import AiRunRegistry
from etsy_listings.ui.api.schemas import (
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
from etsy_listings.ui.api.seo import batch_readiness, listing_proposal
from etsy_listings.ui.api.thumbnails import thumbnail_response
from etsy_listings.ui.batchqueue import RETRYABLE, BatchQueue
from etsy_listings.ui.workspace_locks import WorkspaceLocks
from etsy_listings.workspace.facts import WorkspaceFacts
from etsy_listings.workspace.workspace import Workspace

router = APIRouter(tags=["batches"])

ProposalState = Literal["ready", "stale", "resolved"]


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


def _session(request: Request, session_id: str) -> StagingSession:
    _workspace(request).staging_dir(session_id)  # a bad id is the app-wide 400
    session = _staging(request).load(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"no staging session {session_id!r}")
    return session


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


def _queue(request: Request) -> BatchQueue:
    queue: BatchQueue = request.app.state.batch_queue
    return queue


def _steps(request: Request, row: BatchRow) -> list[WorkflowStep]:
    """A running row's live run, else its last run as it ended."""
    if row.ai == "running":
        registry: AiRunRegistry = request.app.state.ai_run_registry
        run = registry.latest(row.name)
        if run is not None and run.origin == "batch" and not run.finished:
            return run.steps
    return [WorkflowStep.model_validate(step.model_dump()) for step in row.ai_steps]


def _proposal(
    request: Request, row: BatchRow, facts: WorkspaceFacts
) -> tuple[ProposalState | None, list[str]]:
    """The row's listing's cached proposal, judged as the editor judges it
    (A41), so the summary's *Stale: ...* is the drawer's."""
    workspace = _workspace(request)
    store: ProposalStore = request.app.state.proposal_store
    record = store.load(row.name) if has_listing(row) else None
    if record is None:
        return None, []
    try:
        wire = listing_proposal(workspace, row.name, record, facts=facts)
    except (ConfigLoadError, OSError, ValidationError):
        return None, []
    if all(state != "pending" for state in wire.resolution.model_dump().values()):
        return "resolved", []
    if wire.stale.is_stale:
        return "stale", wire.stale.reasons
    return "ready", []


def _batch_detail(request: Request, batch: Batch) -> BatchDetail:
    queue = _queue(request)
    positions = {slot: place for place, slot in enumerate(queue.order(), start=1)}
    facts = WorkspaceFacts.gather(_workspace(request))
    rows = []
    for row in batch.rows:
        proposal, stale = _proposal(request, row, facts)
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
    already spooled the parts to temporary files; `stage_pngs` streams each
    one on -- a PNG to its content-addressed upload, a ZIP to disk and then
    entry by entry out of it -- with a running count (A45)."""
    workspace = _workspace(request)
    if not workspace.listing_template_file(listing_template).is_file():
        raise HTTPException(status_code=404, detail=f"no listing template {listing_template!r}")
    received = [Upload(filename=f.filename or "unnamed.png", stream=f.file) for f in files or []]
    try:
        session = stage_pngs(workspace, _staging(request), listing_template, received)
    except StagingRefused as exc:
        refusal = StagingRefusal(message=exc.message, remedy=exc.remedy)
        raise HTTPException(status_code=422, detail=refusal.model_dump()) from exc
    except ConfigLoadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _staging_detail(request, session)


@router.get("/api/staging/{session_id}", response_model=StagingDetail)
def get_staging(request: Request, session_id: str) -> StagingDetail:
    """A reload reattaches here (spec, *Frozen staging*)."""
    return _staging_detail(request, _session(request, session_id))


@router.patch("/api/staging/{session_id}", response_model=StagingDetail)
def patch_staging(request: Request, session_id: str, body: StagingPatch) -> StagingDetail:
    """Edit the label, type names, remove rows. Every edit moves the
    session's expiry to seven days from now (A46)."""
    now = datetime.now(UTC)
    store = _staging(request)
    with store.lock(session_id):
        session = _session(request, session_id)
        try:
            if body.label is not None:
                session = session.relabelled(body.label.strip() or session.label, now=now)
            for row, name in body.names.items():
                session = session.renamed(row, name, now=now)
            for row in body.remove:
                session = session.removed(row, now=now)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"no staged row {exc.args[0]!r}") from exc
        store.save(session)
    return _staging_detail(request, session)


@router.delete("/api/staging/{session_id}", status_code=204)
def cancel_staging(request: Request, session_id: str) -> Response:
    """Cancel staging: the uploads go at once (A46). The seller's own files
    were never touched."""
    store = _staging(request)
    with store.lock(session_id):
        _session(request, session_id)
        store.remove(session_id)
    return Response(status_code=204)


@router.get("/api/staging/{session_id}/rows/{row}/thumbnail")
def staging_row_thumbnail(request: Request, session_id: str, row: str) -> Response:
    session = _session(request, session_id)
    try:
        path = upload_path(_workspace(request), session, row)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"no staged row {row!r}") from exc
    return thumbnail_response(path)


@router.post(
    "/api/staging/{session_id}/confirm",
    response_model=BatchDetail,
    responses={409: {"description": "The session cannot be confirmed yet"}},
)
def confirm_staging(request: Request, session_id: str) -> BatchDetail:
    """Create N listings (UI doc §6). Repeating it -- a double click, a retry
    after a dropped response -- finishes the same batch rather than making a
    second one (A39)."""
    workspace = _workspace(request)
    workspace.staging_dir(session_id)
    if _batches(request).load(session_id) is None:
        # Spec, *Design validation*: a batch is not knowingly created into a
        # queue that cannot run. A confirm finishing a batch that exists
        # already is not asked again -- its listings are half made.
        blocked = _ai_blocked(request)
        if blocked is not None:
            raise HTTPException(
                status_code=409, detail=f"AI drafting can't run yet. {blocked.message}"
            )
    try:
        batch = confirm(
            workspace,
            _staging(request),
            _batches(request),
            session_id,
            lock=_locks(request).listing,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"no staging session {session_id!r}") from exc
    except ConfirmRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _queue(request).wake()
    return _batch_detail(request, batch)


def _batch(request: Request, batch_id: str) -> Batch:
    _workspace(request).batch_file(batch_id)
    batch = _batches(request).load(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"no batch {batch_id!r}")
    return batch


@router.get("/api/batches/{batch_id}", response_model=BatchDetail)
def get_batch(request: Request, batch_id: str) -> BatchDetail:
    return _batch_detail(request, _batch(request, batch_id))


@router.post(
    "/api/batches/{batch_id}/rows/{row}/retry",
    response_model=BatchDetail,
    responses={409: {"description": "The row has nothing to retry"}},
)
def retry_batch_row(request: Request, batch_id: str, row: str) -> BatchDetail:
    """Retry one row (UI doc §7): its creation, if that failed -- which
    queues it once it exists -- else its AI, keeping the saved brief (A40)."""
    batch = _batch(request, batch_id)
    target = next((r for r in batch.rows if r.id == row), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"no batch row {row!r}")
    if target.creation == "failed":
        _retry_creation(request, batch_id, {row})
    elif target.ai in RETRYABLE and not target.deleted:
        _queue(request).retry(batch_id, row)
    else:
        raise HTTPException(status_code=409, detail=f"{target.name} has nothing to retry")
    return _batch_detail(request, _batch(request, batch_id))


def _retry_creation(request: Request, batch_id: str, rows: set[str]) -> None:
    for row in rows:
        retry_row(
            _workspace(request),
            _staging(request),
            _batches(request),
            batch_id,
            row,
            lock=_locks(request).listing,
        )
    _queue(request).wake()


@router.post("/api/batches/{batch_id}/retry", response_model=BatchDetail)
def retry_batch(request: Request, batch_id: str) -> BatchDetail:
    """**Retry N failed**: every row whose creation or AI failed."""
    batch = _batch(request, batch_id)
    _retry_creation(request, batch_id, {r.id for r in batch.rows if r.creation == "failed"})
    _queue(request).retry(batch_id)
    return _batch_detail(request, _batch(request, batch_id))


@router.post("/api/batches/{batch_id}/cancel", response_model=BatchDetail)
def cancel_batch(request: Request, batch_id: str) -> BatchDetail:
    """**Cancel batch** (spec, *Cancellation and deletion*): queued rows are
    stopped and running ones asked to stop. Everything written stays."""
    _batch(request, batch_id)
    _queue(request).cancel(batch_id)
    return _batch_detail(request, _batch(request, batch_id))


@router.post("/api/batches/{batch_id}/resume", response_model=BatchDetail)
def resume_batch(request: Request, batch_id: str) -> BatchDetail:
    """**Resume**: stopped and cancelled rows join the queue again."""
    _batch(request, batch_id)
    _queue(request).resume(batch_id)
    return _batch_detail(request, _batch(request, batch_id))


# ------------------------------------------------ review and the batch index


@router.get("/api/batches", response_model=list[BatchIndexEntry])
def list_batches(request: Request) -> list[BatchIndexEntry]:
    """Recent batches (UI doc §2): every batch, and every staging session
    not confirmed yet, newest first, each with its derived status. Listing
    them sweeps expired staging first (A46), so a row never offers a
    session that has gone."""
    staging = _staging(request)
    staging.sweep(now=datetime.now(UTC))
    batches = _batches(request).all()
    confirmed = {batch.id for batch in batches}
    entries = [_index_entry(batch) for batch in batches]
    for session_id in _workspace(request).staging_ids():
        # A batch keeps its session's id, and a confirmed session stays
        # until every row is materialised (A46): that one is the batch's.
        session = staging.load(session_id) if session_id not in confirmed else None
        if session is not None:
            entries.append(
                BatchIndexEntry(
                    kind="staging",
                    id=session.id,
                    label=session.label,
                    listing_template=session.listing_template,
                    created_at=session.created_at,
                    status="staging",
                    designs=len(session.rows),
                    expires_at=session.expires_at,
                )
            )
    return sorted(entries, key=lambda entry: (entry.created_at, entry.id), reverse=True)


def _index_entry(batch: Batch) -> BatchIndexEntry:
    counts = standing(batch.rows)
    return BatchIndexEntry(
        kind="batch",
        id=batch.id,
        label=batch.label,
        listing_template=batch.listing_template,
        created_at=batch.created_at,
        status=counts.status,
        designs=len(batch.rows),
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
    store = _batches(request)
    with store.lock(batch_id):
        batch = _batch(request, batch_id)
        label = body.label.strip()
        if label and label != batch.label:
            batch = batch.model_copy(update={"label": label})
            store.save(batch)
    return _batch_detail(request, batch)


@router.delete("/api/batches/{batch_id}", status_code=204)
def delete_batch(request: Request, batch_id: str) -> Response:
    """Delete batch record (spec, *Cancellation and deletion*): its queued
    and running work is cancelled first, then only the record goes -- its
    rows, review flags and queue state, and the frozen template beside it.
    Designs, listings, briefs and proposals are the workspace's and stay."""
    _batch(request, batch_id)
    queue = _queue(request)
    queue.cancel(batch_id)
    store = _batches(request)
    with store.lock(batch_id):
        store.remove(batch_id)
    queue.wake()
    return Response(status_code=204)


@router.put(
    "/api/batches/{batch_id}/rows/{row}/reviewed",
    response_model=BatchDetail,
    responses={409: {"description": "The row has no listing to review yet"}},
)
def set_reviewed(request: Request, batch_id: str, row: str, body: ReviewedRequest) -> BatchDetail:
    """Mark reviewed / Mark needs review (spec, *Review workflow*). Refused
    for a row still queued or drafting, deleted, or never created."""
    _batch(request, batch_id)
    try:
        batch = _batches(request).review(batch_id, row, reviewed=body.reviewed)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"no batch row {row!r}") from exc
    except NotReviewable as exc:
        raise HTTPException(
            status_code=409, detail=f"{exc.args[0]} has no listing to review yet"
        ) from exc
    return _batch_detail(request, batch)


@router.get("/api/batches/{batch_id}/rows/{row}/thumbnail")
def batch_row_thumbnail(request: Request, batch_id: str, row: str) -> Response:
    """A row that was never created has no listing design to show, so the
    summary shows the upload it was made from, kept beside the batch for
    Retry (A46)."""
    batch = _batch(request, batch_id)
    try:
        path = row_upload(_workspace(request), batch, row)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"no batch row {row!r}") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"batch row {row!r} has no upload kept")
    return thumbnail_response(path)


@router.get("/api/listings/{name}/batch", response_model=ListingBatch | None)
def listing_batch(request: Request, name: str) -> ListingBatch | None:
    """The batch that made ``name``, for the editor's row above the head
    (UI doc §8), or ``null``. A row names its listing exactly, as the rename
    and delete hooks match it (A42); a deleted row is not the listing's.
    Should two batches both claim it, the newer wins."""
    _workspace(request).listing_dir(name)  # a bad name is the app-wide 400
    newest = sorted(_batches(request).all(), key=lambda b: (b.created_at, b.id), reverse=True)
    for batch in newest:
        for candidate in batch.rows:
            if candidate.name == name and has_listing(candidate):
                return ListingBatch(
                    batch_id=batch.id,
                    label=batch.label,
                    row_id=candidate.id,
                    reviewed=candidate.reviewed,
                    reviewable=reviewable(candidate),
                )
    return None
