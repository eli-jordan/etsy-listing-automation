"""The AI runs resource (market-seo.md, *AI runs*; the implementation plan's
*Run contract*).

```
POST   /api/ai/runs              {listing, draft_brief} -> 202 AiRunSummary
                                 | 409 {active_run} | 409 {reason}
GET    /api/ai/runs?listing=     the listing's current or most recent run, or 404
GET    /api/ai/runs/{id}         AiRunDetail: phase, steps, events so far
GET    /api/ai/runs/{id}/events  text/event-stream; replays after Last-Event-ID
DELETE /api/ai/runs/{id}         cancel; 409 if already finished
```

``POST`` re-checks readiness here, whatever the browser last saw
(``seo.readiness`` with the run's rules). The chain itself is
``ui/airuns/runner.py``'s, on its own thread; this module only starts,
reads and cancels runs.

**The SSE bridge** is ``ui/api/runs.py``'s: a blocking wait on the run's
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

from etsy_listings.ui.airuns.events import (
    AiRunDetail,
    AiRunRefusal,
    AiRunSummary,
    AnyAiRunEvent,
    CreateAiRunRequest,
)
from etsy_listings.ui.airuns.registry import AiRun, AiRunRegistry, Conflict
from etsy_listings.ui.airuns.runner import AiRunner
from etsy_listings.ui.api.runs import last_event_id
from etsy_listings.ui.api.seo import readiness
from etsy_listings.workspace.workspace import Workspace

router = APIRouter(prefix="/api/ai/runs", tags=["ai-runs"])

_EVENT_WAIT_TIMEOUT = 1.0
"""One SSE poll's longest block, as in ``ui/api/runs.py``."""


def _registry(request: Request) -> AiRunRegistry:
    registry: AiRunRegistry = request.app.state.ai_run_registry
    return registry


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
    registry = _registry(request)
    workspace: Workspace = request.app.state.workspace
    if not workspace.listing_file(body.listing).is_file():
        raise HTTPException(status_code=404, detail=f"no listing {body.listing!r}")

    active = registry.latest(body.listing)
    if active is not None and not active.finished:
        return _refused(AiRunRefusal(active_run=active.id))
    providers = request.app.state.seo_provider_factory(workspace)
    ready = readiness(
        workspace, workspace.load_listing(body.listing), providers, draft_brief=body.draft_brief
    )
    if not ready.ready:
        return _refused(AiRunRefusal(reason=ready.reason))

    run = registry.create(body.listing, draft_brief=body.draft_brief)
    if isinstance(run, Conflict):
        return _refused(AiRunRefusal(active_run=run.active_run))
    runner: AiRunner = request.app.state.ai_runner
    runner.start(run)
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
