from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from etsy_listings.core.application.ai.coordinator import AiCoordinator
from etsy_listings.core.application.ai.registry import AiRun, AiRunRegistry, Conflict
from etsy_listings.core.application.refusals import (
    AiNotReadyError,
    ListingDeployingError,
    ListingDraftingInBatchError,
)
from etsy_listings.server.api.schemas import (
    AiRunDetail,
    AiRunRefusal,
    AiRunSummary,
    CreateAiRunRequest,
)
from etsy_listings.server.api.sse import event_stream

router = APIRouter(prefix="/api/ai/runs", tags=["ai-runs"])

BATCH_PENDING = "batch_pending"
"""The refusal's ``reason`` while batch work owns the listing, a code
the editor words itself rather than a sentence."""

DEPLOYING = "deploying"
"""The refusal's ``reason`` while a UI plan or apply holds the listing
: deploying takes precedence over AI."""

"""One SSE poll's longest block, as in ``server/api/runs.py``."""


def _ai(request: Request) -> AiCoordinator:
    ai: AiCoordinator = request.app.state.ai
    return ai


def _registry(request: Request) -> AiRunRegistry:
    return _ai(request).registry


def _run(request: Request, run_id: str) -> AiRun:
    run = _registry(request).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"no AI run {run_id!r}")
    return run


def _summary(request: Request, run: AiRun) -> AiRunSummary:
    return AiRunSummary(
        id=run.id,
        listing=run.listing,
        draft_brief=run.draft_brief,
        origin=run.origin,
        phase=run.phase,
        steps=run.steps,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        waiting_for_backup=_ai(request).waiting_for_backup(run),
    )


def _refused(refusal: AiRunRefusal) -> JSONResponse:
    return JSONResponse(status_code=409, content=refusal.model_dump())


@router.post(
    "",
    status_code=202,
    response_model=AiRunSummary,
    responses={404: {}, 409: {"model": AiRunRefusal}},
)
def create_ai_run(request: Request, body: CreateAiRunRequest) -> AiRunSummary | JSONResponse:
    """Start a run for a saved listing. A ``409`` either names the active run
    to reattach to, or gives the readiness rule that failed."""
    try:
        run = _ai(request).start_run(body.listing, draft_brief=body.draft_brief)
    except ListingDeployingError:
        return _refused(AiRunRefusal(reason=DEPLOYING))
    except ListingDraftingInBatchError:
        return _refused(AiRunRefusal(reason=BATCH_PENDING))
    except AiNotReadyError as exc:
        return _refused(AiRunRefusal(reason=exc.reason))
    if isinstance(run, Conflict):
        return _refused(AiRunRefusal(active_run=run.active_run))
    return _summary(request, run)


@router.get("", response_model=AiRunSummary, responses={404: {}})
def find_ai_run(request: Request, listing: str) -> AiRunSummary:
    """The listing's running or most recent run -- what the editor
    reattaches to after a reload."""
    run = _registry(request).latest(listing)
    if run is None:
        raise HTTPException(status_code=404, detail=f"no AI run for {listing!r}")
    return _summary(request, run)


@router.get("/{run_id}", response_model=AiRunDetail, responses={404: {}})
def get_ai_run(request: Request, run: Annotated[AiRun, Depends(_run)]) -> AiRunDetail:
    with run.condition:
        return AiRunDetail(**_summary(request, run).model_dump(), events=list(run.events))


@router.delete("/{run_id}", response_model=AiRunSummary, responses={404: {}, 409: {}})
def cancel_ai_run(request: Request, run: Annotated[AiRun, Depends(_run)]) -> AiRunSummary:
    """Cancel: the run's provider subprocess tree is killed and research
    starts no new call. The run ends ``cancelled`` on its own thread
    shortly after; a brief or snapshot already written stays."""
    if not run.request_stop("cancelled"):
        raise HTTPException(status_code=409, detail="this AI run has already finished")
    return _summary(request, run)


@router.get("/{run_id}/events", responses={404: {}})
def stream_ai_run_events(
    run: Annotated[AiRun, Depends(_run)], request: Request
) -> StreamingResponse:
    return event_stream(request, run, lambda event: event.seq)
