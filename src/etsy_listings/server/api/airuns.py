"""The AI runs resource (features/market-seo-20260924/spec.md, *AI runs*; the implementation plan's
*Run contract*).

```
POST /api/ai/runs {listing, draft_brief} -> 202 AiRunSummary
                                 | 409 {active_run} | 409 {reason}
                                 | 409 {reason: "batch_pending"}
                                 | 409 {reason: "deploying"}
GET /api/ai/runs?listing= the listing's current or most recent run, or 404
GET /api/ai/runs/{id} AiRunDetail: phase, steps, events so far
GET /api/ai/runs/{id}/events text/event-stream; replays after Last-Event-ID
DELETE /api/ai/runs/{id} cancel; 409 if already finished
```

``POST`` asks core's AI coordinator (``core/application/ai/coordinator.py``)
to start the run, which re-checks readiness whatever the browser last saw;
this module maps its refusals to the codes above. The chain itself is
``core/application/ai/runner.py``'s, on its own thread; this module only
starts, reads and cancels runs.

**The SSE bridge** is ``server/api/runs.py``'s: a blocking wait on the run's
condition, awaited through ``run_in_executor`` with a short timeout so the
generator notices a client leaving. A client leaving ends the stream and
nothing else -- only ``DELETE`` cancels.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from etsy_listings.core.application.ai.coordinator import AiCoordinator
from etsy_listings.core.application.ai.events import AnyAiRunEvent
from etsy_listings.core.application.ai.registry import AiRun, AiRunRegistry, Conflict
from etsy_listings.core.application.refusals import (
    AiNotReady,
    ListingDeploying,
    ListingDraftingInBatch,
    ListingMissing,
)
from etsy_listings.server.api.runs import last_event_id
from etsy_listings.server.api.schemas import (
    AiRunDetail,
    AiRunRefusal,
    AiRunSummary,
    CreateAiRunRequest,
)

router = APIRouter(prefix="/api/ai/runs", tags=["ai-runs"])

BATCH_PENDING = "batch_pending"
"""The refusal's ``reason`` while batch work owns the listing, a code
the editor words itself rather than a sentence."""

DEPLOYING = "deploying"
"""The refusal's ``reason`` while a UI plan or apply holds the listing
: deploying takes precedence over AI."""

_EVENT_WAIT_TIMEOUT = 1.0
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


Existing = Annotated[AiRun, Depends(_run)]


def _summary(run: AiRun) -> AiRunSummary:
    return AiRunSummary(
        id=run.id,
        listing=run.listing,
        draft_brief=run.draft_brief,
        origin=run.origin,
        phase=run.phase,
        steps=run.steps,
        created_at=run.created_at,
        finished_at=run.finished_at,
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
    except ListingMissing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ListingDeploying:
        return _refused(AiRunRefusal(reason=DEPLOYING))
    except ListingDraftingInBatch:
        return _refused(AiRunRefusal(reason=BATCH_PENDING))
    except AiNotReady as exc:
        return _refused(AiRunRefusal(reason=exc.reason))
    if isinstance(run, Conflict):
        return _refused(AiRunRefusal(active_run=run.active_run))
    return _summary(run)


@router.get("", response_model=AiRunSummary, responses={404: {}})
def find_ai_run(request: Request, listing: str) -> AiRunSummary:
    """The listing's running or most recent run -- what the editor
    reattaches to after a reload."""
    run = _registry(request).latest(listing)
    if run is None:
        raise HTTPException(status_code=404, detail=f"no AI run for {listing!r}")
    return _summary(run)


@router.get("/{run_id}", response_model=AiRunDetail, responses={404: {}})
def get_ai_run(run: Existing) -> AiRunDetail:
    with run.condition:
        return AiRunDetail(**_summary(run).model_dump(), events=list(run.events))


@router.delete("/{run_id}", response_model=AiRunSummary, responses={404: {}, 409: {}})
def cancel_ai_run(run: Existing) -> AiRunSummary:
    """Cancel: the run's provider subprocess tree is killed and research
    starts no new call. The run ends ``cancelled`` on its own thread
    shortly after; a brief or snapshot already written stays."""
    if not run.request_stop("cancelled"):
        raise HTTPException(status_code=409, detail="this AI run has already finished")
    return _summary(run)


def _sse_frame(event: AnyAiRunEvent) -> bytes:
    return f"id: {event.seq}\nevent: {event.type}\ndata: {event.model_dump_json()}\n\n".encode()


async def sse_events(request: Request, run: AiRun, after_seq: int) -> AsyncIterator[bytes]:
    """Every event past ``after_seq``, then each new one, until the run's
    last. Returns when the client has gone; the run is not touched."""
    loop = asyncio.get_running_loop()
    next_seq = after_seq
    while True:
        if await request.is_disconnected():
            return

        def wait(after: int = next_seq) -> tuple[list[AnyAiRunEvent], bool]:
            return run.wait_for_events(after, timeout=_EVENT_WAIT_TIMEOUT)

        pending, done = await loop.run_in_executor(None, wait)
        for event in pending:
            next_seq = event.seq
            yield _sse_frame(event)
        if done:
            return


@router.get("/{run_id}/events", responses={404: {}})
def stream_ai_run_events(run: Existing, request: Request) -> StreamingResponse:
    return StreamingResponse(
        sse_events(request, run, last_event_id(request)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
