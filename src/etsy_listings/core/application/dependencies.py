"""The small interfaces listing operations take their coordination through.

Each exists because the object behind it lives outside core for now and core
must never import the server (ADR-0052): the UI process's AI run registry
(``server/airuns``, until PR 9 of the module-structure plan), its batch queue
and AI readiness (likewise PR 9) and its memo of Etsy listing states
(``server/api/etsystate.py``, request-serving read infrastructure that may
stay there; plan, PR 7). They describe only what an operation calls, so the
existing objects satisfy them structurally and are passed in unchanged; there
is no adapter class to keep in step.

The write locks are core's own (``workspace_locks.WorkspaceLocks``, since
PR 8), so operations take that class directly: one implementation and no
second one in sight, which left an interface for it nothing to vary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Literal, Protocol

EtsyStates = Callable[[Sequence[int]], Mapping[int, str | None]]
"""Etsy's ``state`` for each listing id asked about, ``None`` where unknown.

Status, gestures and the published-deletion refusal all turn on it, and only
Etsy knows it. Asked once per read with every id the read needs, so a table
costs one round trip; a lookup that cannot ask (no credentials, no shop)
answers ``None``, which reads as not published."""


class StoppableRun(Protocol):
    def request_stop(self, reason: Literal["cancelled"]) -> object: ...


class ListingAiRuns(Protocol):
    """The AI run registry, as deleting or renaming a listing touches it: a
    deleted listing's active run is asked to stop, and either way the name's
    finished run is forgotten so a new listing given it does not reattach."""

    def latest(self, listing: str) -> StoppableRun | None: ...

    def forget(self, listing: str) -> None: ...


YieldToDeploy = Callable[[Sequence[str]], AbstractContextManager[None]]
"""The deploy-to-AI handoff (ADR-0050: deploying takes precedence over AI
work): how a deployment run takes its listings from AI work before it reads
them. ``BatchQueue.yield_to_deploy`` in the UI process, the server's until
PR 9 of the module-structure plan moves AI coordination. It returns once the
listings' AI work has stopped, and holds them until the ``with`` ends."""


AiBlocked = Callable[[], str | None]
"""Why a batch created now could not draft -- a prompt, a ready provider or
Etsy market access missing -- or ``None`` while it could. AI readiness is
the server's until PR 9 of the module-structure plan moves it; confirming a
batch only needs the answer, asked once per new batch."""


class BatchQueueControl(Protocol):
    """The UI process's batch queue (``server/batchqueue.py``, until PR 9),
    as the seller's batch controls steer it. A confirm or a creation retry
    wakes it for the rows just queued; the rest change which rows it will
    start (ADR-0048). Reading its order is the server's projection."""

    def wake(self) -> None: ...

    def retry(self, batch_id: str, row_id: str | None = None) -> object: ...

    def cancel(self, batch_id: str) -> object: ...

    def resume(self, batch_id: str) -> object: ...
