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
