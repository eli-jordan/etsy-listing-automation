"""The one small interface listing operations take a dependency through.

It exists because the object behind it is the server's and core must never
import the server (ADR-0052): the UI process's memo of Etsy listing states
(``server/api/etsystate.py``), request-serving read infrastructure that stays
there (plan, PR 7). It describes only what an operation calls, so the memo
satisfies it as it stands and there is no adapter class to keep in step; a
test answers with a fixed Etsy instead.

Everything else an operation coordinates through is core's own, so it takes
that class directly: the write locks (``workspace_locks.WorkspaceLocks``,
since PR 8), and the AI run registry, the batch queue, AI readiness and the
deploy-to-AI handoff (``ai/``, since PR 9). One implementation each and no
second one in sight left an interface for them nothing to vary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

EtsyStates = Callable[[Sequence[int]], Mapping[int, str | None]]
"""Etsy's ``state`` for each listing id asked about, ``None`` where unknown.

Status, gestures and the published-deletion refusal all turn on it, and only
Etsy knows it. Asked once per read with every id the read needs, so a table
costs one round trip; a lookup that cannot ask (no credentials, no shop)
answers ``None``, which reads as not published."""
