"""Staging and batch endpoints (batch plan PR 2; A37-A39, A45, A46): stage
loose PNGs against a listing template, review and edit the session, cancel it
or confirm it, then read the batch confirming made.

The rules are `batches`'; this module decides only what each answer is on
the wire:

* An upload refused before staging is a ``422`` whose ``detail`` is the
  sentence and the remedy (`StagingRefusal`), with nothing on disk.
* A session that cannot be confirmed yet is a ``409`` with the sentence, and
  nothing is created.
* An id nobody holds -- a session, a batch or a row -- is a ``404``. An id
  that is not a single path segment is the app-wide ``400``.

Both stores and the per-listing locks are the app's (`app.state`), so a
confirm and an editor's create of the same name wait for each other (A38).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from etsy_listings.batches import (
    Batch,
    BatchStore,
    ConfirmRefused,
    StagingRefused,
    StagingSession,
    StagingStore,
    Upload,
    confirm,
    retry_row,
    review,
    stage_pngs,
    upload_path,
)
from etsy_listings.config.errors import ConfigLoadError
from etsy_listings.ui.api.schemas import (
    BatchDetail,
    BatchRowDetail,
    StagingDetail,
    StagingPatch,
    StagingRefusal,
    StagingRowDetail,
)
from etsy_listings.ui.api.thumbnails import thumbnail_response
from etsy_listings.ui.workspace_locks import WorkspaceLocks
from etsy_listings.workspace.workspace import Workspace

router = APIRouter(tags=["batches"])


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


def _staging_detail(workspace: Workspace, session: StagingSession) -> StagingDetail:
    reviewed = review(workspace, session)
    return StagingDetail(
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
            )
            for row in reviewed.rows
        ],
    )


def _batch_detail(batch: Batch) -> BatchDetail:
    return BatchDetail(
        id=batch.id,
        label=batch.label,
        listing_template=batch.listing_template,
        created_at=batch.created_at,
        rows=[
            BatchRowDetail(
                id=row.id,
                sources=row.sources,
                name=row.name,
                design=row.design,
                creation=row.creation,
                error=row.error,
            )
            for row in batch.rows
        ],
    )


@router.post(
    "/api/staging",
    response_model=StagingDetail,
    responses={422: {"model": StagingRefusal}},
)
def create_staging(
    request: Request, listing_template: str = Form(...), files: list[UploadFile] | None = None
) -> StagingDetail:
    """Stage loose PNGs (spec, *Accepted input*). Starlette has already
    spooled the parts to temporary files; `stage_pngs` streams each one on to
    its content-addressed upload with a running count (A45). A ZIP is
    refused as *coming soon* until batch plan PR 7."""
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
    return _staging_detail(workspace, session)


@router.get("/api/staging/{session_id}", response_model=StagingDetail)
def get_staging(request: Request, session_id: str) -> StagingDetail:
    """A reload reattaches here (spec, *Frozen staging*)."""
    return _staging_detail(_workspace(request), _session(request, session_id))


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
    return _staging_detail(_workspace(request), session)


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
    return _batch_detail(batch)


def _batch(request: Request, batch_id: str) -> Batch:
    _workspace(request).batch_file(batch_id)
    batch = _batches(request).load(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"no batch {batch_id!r}")
    return batch


@router.get("/api/batches/{batch_id}", response_model=BatchDetail)
def get_batch(request: Request, batch_id: str) -> BatchDetail:
    return _batch_detail(_batch(request, batch_id))


@router.post("/api/batches/{batch_id}/rows/{row}/retry", response_model=BatchDetail)
def retry_batch_row(request: Request, batch_id: str, row: str) -> BatchDetail:
    """Retry a row whose creation failed (UI doc §7). The AI half of Retry
    arrives with the batch queue (batch plan PR 4)."""
    _batch(request, batch_id)
    try:
        batch = retry_row(
            _workspace(request),
            _staging(request),
            _batches(request),
            batch_id,
            row,
            lock=_locks(request).listing,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"no batch row {row!r}") from exc
    return _batch_detail(batch)
