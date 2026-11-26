"""Server-sent event streams over a run's blocking event log.

The stream awaits ``wait_for_events`` in an executor with a short timeout so it
notices a client going away, which ends only its stream; a later connection
replays the run from ``Last-Event-ID``."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Protocol

from fastapi import Request
from fastapi.responses import StreamingResponse

EVENT_WAIT_TIMEOUT = 1.0


class StreamedEvent(Protocol):
    @property
    def type(self) -> str: ...

    def model_dump_json(self) -> str: ...


class EventLog[E](Protocol):
    def wait_for_events(self, after: int, /, *, timeout: float) -> tuple[list[E], bool]: ...


def last_event_id(request: Request) -> int:
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


def event_stream[E: StreamedEvent](
    request: Request, log: EventLog[E], cursor: Callable[[E], int]
) -> StreamingResponse:
    """``text/event-stream`` of every event past ``Last-Event-ID``, then each
    new one, until the log says it is done. ``cursor`` is an event's id."""
    return StreamingResponse(
        _frames(request, log, cursor, last_event_id(request)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _frames[E: StreamedEvent](
    request: Request, log: EventLog[E], cursor: Callable[[E], int], after: int
) -> AsyncIterator[bytes]:
    loop = asyncio.get_running_loop()
    next_id = after
    while True:
        if await request.is_disconnected():
            return

        def wait(after: int = next_id) -> tuple[list[E], bool]:
            return log.wait_for_events(after, timeout=EVENT_WAIT_TIMEOUT)

        pending, done = await loop.run_in_executor(None, wait)
        for event in pending:
            next_id = cursor(event)
            data = event.model_dump_json()
            yield f"id: {next_id}\nevent: {event.type}\ndata: {data}\n\n".encode()
        if done:
            return
