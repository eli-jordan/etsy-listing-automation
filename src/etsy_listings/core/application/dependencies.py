"""The small interfaces listing operations take their coordination through.

Each exists because the object behind it lives outside core for now -- the
UI process's write locks in ``server/workspace_locks.py`` until PR 8 of the
module-structure plan moves them -- and core must never import the server
(ADR-0052). They describe only what an operation calls, so the existing
objects satisfy them structurally and are passed in unchanged; there is no
adapter class to keep in step.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol


class ListingLocks(Protocol):
    """Per-listing write locks: ``WorkspaceLocks`` in the UI process.

    Held around a whole read-merge-write or name check and move. Several
    names -- a rename's old and new -- are taken together, in one order, so
    two callers naming the same pair cannot deadlock. An operation re-checks
    the listing still exists once it holds the lock: a rename or delete that
    held it first may have moved it.
    """

    def listing(self, name: str, *more: str) -> AbstractContextManager[None]: ...
