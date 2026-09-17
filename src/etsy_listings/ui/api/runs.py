"""The runs resource's six endpoints (A33, decision 7).

```
POST   /api/runs              {kind, listings, expect?} -> 202 RunSummary | 409 {active_run}
GET    /api/runs?listing=     active and recent runs for a listing
GET    /api/runs/{id}         RunDetail: phase, listings, events so far
GET    /api/runs/{id}/events  text/event-stream; replays after Last-Event-ID
DELETE /api/runs/{id}         cancel a queued or running plan; 409 for apply
POST   /api/runs/{id}/seen    the result of a finished run has been looked at
```

Every write here is a call into :mod:`etsy_listings.ui.runs.registry` -- this
module never decides whether a run may start, only how that decision is
carried over HTTP. Nothing here computes a diff or runs a run either
(CLAUDE.md's invariants): the FIFO worker thread in ``ui/runs/executor.py``
does both, on its own time, and these endpoints only ever read or nudge the
:class:`~etsy_listings.ui.runs.registry.Run` it is working on.

**The SSE bridge.** :func:`_wait_for_events` is a plain, blocking method on
:class:`~etsy_listings.ui.runs.registry.Run` -- it has to be, since the
executor thread that appends events is a plain thread, not a coroutine. The
route awaits it through ``loop.run_in_executor``, which is the stdlib's own
way to run a blocking call without stalling the event loop, so no new
dependency (``sse-starlette`` or similar) is needed: a short, bounded
``timeout`` on each wait is what turns "block until notified" into something
an ``async def`` generator can yield control back from periodically, both to
check the client is still there and to let the surrounding ASGI server keep
serving other requests meanwhile.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from etsy_listings.ui.api.schemas import CreateRunRequest, RunDetail, RunSummary
from etsy_listings.ui.runs.events import AnyRunEvent
from etsy_listings.ui.runs.registry import Conflict, Run, RunRegistry

router = APIRouter(prefix="/api/runs", tags=["runs"])

_EVENT_WAIT_TIMEOUT = 1.0
"""How long one SSE poll blocks the executor thread pool before yielding
control back to the event loop -- short enough that a client disconnecting,
or the surrounding server shutting down, is noticed promptly; long enough that
an idle stream is not a busy loop."""


def _registry(request: Request) -> RunRegistry:
    registry: RunRegistry = request.app.state.run_registry
    return registry


@dataclass(frozen=True)
class Target:
    registry: RunRegistry
    run: Run


def target(request: Request, run_id: str) -> Target:
    registry = _registry(request)
    run = registry.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"no run {run_id!r}")
    return Target(registry=registry, run=run)


Existing = Annotated[Target, Depends(target)]


def _summary(run: Run) -> RunSummary:
    return RunSummary(
        id=run.id, kind=run.kind, listings=list(run.listings), phase=run.phase, seen=run.seen
    )


def _detail(run: Run) -> RunDetail:
    return RunDetail(**_summary(run).model_dump(), events=list(run.events))


@router.post("", status_code=202, response_model=RunSummary)
def create_run(request: Request, body: CreateRunRequest) -> RunSummary | JSONResponse:
    """A ``409`` names the run already holding one of these listings, so the
    caller can reattach to it (``GET /api/runs/{active_run}``) instead of
    retrying into the same refusal."""
    registry = _registry(request)
    result = registry.create(body.kind, body.listings, expect=body.expect)
    if isinstance(result, Conflict):
        return JSONResponse(status_code=409, content={"active_run": result.active_run})
    return _summary(result)


@router.get("", response_model=list[RunSummary])
def list_runs(request: Request, listing: str | None = None) -> list[RunSummary]:
    """``listing`` narrows to that listing's current run (active, or finished
    and not yet superseded -- decision 7's retention). Omitted, every run this
    process still remembers, for a future workspace-wide view."""
    registry = _registry(request)
    runs = registry.for_listing(listing) if listing is not None else registry.all_runs()
    return [_summary(run) for run in runs]


@router.get("/{run_id}", response_model=RunDetail)
def get_run(target: Existing) -> RunDetail:
    return _detail(target.run)


@router.delete("/{run_id}", response_model=RunSummary)
def cancel_run(target: Existing) -> RunSummary:
    """Cancel a queued or running **plan**. An ``apply`` is refused
    unconditionally (decision 8: Back leaves, it never cancels one), and so is
    a run that has already finished."""
    result = target.registry.cancel(target.run.id)
    if result is False:
        raise HTTPException(status_code=409, detail="this run cannot be cancelled")
    return _summary(target.run)


@router.post("/{run_id}/seen", response_model=RunSummary)
def mark_seen(target: Existing) -> RunSummary:
    target.run.mark_seen()
    return _summary(target.run)


def _last_event_id(request: Request) -> int:
    """``Last-Event-ID``, the header ``EventSource`` sends on reconnect --
    ``0`` for a fresh connection or a header that is not a plain integer, both
    of which mean "replay everything"."""
    raw = request.headers.get("last-event-id")
    if raw is None:
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


def _sse_frame(event: AnyRunEvent) -> bytes:
    return f"id: {event.id}\nevent: {event.type}\ndata: {event.model_dump_json()}\n\n".encode()


async def _sse_events(request: Request, run: Run, after_id: int) -> AsyncIterator[bytes]:
    loop = asyncio.get_event_loop()
    next_id = after_id
    while True:
        if await request.is_disconnected():
            return

        def wait(after: int = next_id) -> tuple[list[AnyRunEvent], bool]:
            return run.wait_for_events(after, timeout=_EVENT_WAIT_TIMEOUT)

        pending, done = await loop.run_in_executor(None, wait)
        for event in pending:
            next_id = event.id
            yield _sse_frame(event)
        if done:
            return


@router.get("/{run_id}/events")
def stream_events(target: Existing, request: Request) -> StreamingResponse:
    """``text/event-stream`` over this run's own event buffer -- every event
    already recorded past ``Last-Event-ID``, then whatever the worker thread
    appends next, until the run reaches a terminal phase."""
    after_id = _last_event_id(request)
    return StreamingResponse(
        _sse_events(request, target.run, after_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
