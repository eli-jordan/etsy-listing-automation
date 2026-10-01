"""The small interfaces listing operations take their coordination through.

Each exists because the object behind it lives outside core for now and core
must never import the server (ADR-0052): the UI process's write locks
(``server/workspace_locks.py``, until PR 8 of the module-structure plan),
its AI run registry (``server/airuns``, until PR 9) and its memo of Etsy
listing states (``server/api/etsystate.py``, request-serving read
infrastructure that may stay there; plan, PR 7). They describe only what an
operation calls, so the existing objects satisfy them structurally and are
passed in unchanged; there is no adapter class to keep in step.
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


class ListingLocks(Protocol):
    """Per-listing write locks: ``WorkspaceLocks`` in the UI process.

    Held around a whole read-merge-write or name check and move. Several
    names -- a rename's old and new -- are taken together, in one order, so
    two callers naming the same pair cannot deadlock. An operation re-checks
    the listing still exists once it holds the lock: a rename or delete that
    held it first may have moved it.
    """

    def listing(self, name: str, *more: str) -> AbstractContextManager[None]: ...


class ListingTemplateLocks(Protocol):
    """Per-listing-template write locks: ``WorkspaceLocks`` again, in a key
    space of their own (plan, PR 7). Held around a template's name check and
    write, a ``PUT``'s re-check and write, a rename's move and a delete --
    and around staging's capture of a template's frozen content, so a batch
    never freezes a half-written template (ADR-0047)."""

    def listing_template(self, name: str, *more: str) -> AbstractContextManager[None]: ...


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
