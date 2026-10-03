"""Per-listing-template write locks for the UI process.

Creating a listing template checks that its name is free and then writes,
and a ``PUT`` re-checks that the template still exists before writing. Two of
those interleaved, or one interleaved with a rename, would recreate a
template under a name that has just moved, or write over one just created.
Batch staging holds the same lock while it captures a template's frozen
content, so a batch never freezes a half-written template (ADR-0047).

Listings do not lock here. Their lock belongs to their document
(``core/workspace/listing_documents.py``), so the engine and batch creation
take it as the editor does.

The locks are in memory and per process. They do not cover the CLI running
against the same workspace at the same time, which nothing in the tool has
ever guarded.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager


class WorkspaceLocks:
    """One lock per listing template name. Each lock is made on first use
    and kept for the life of the process, which costs a few hundred bytes
    per template a seller has ever touched."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    @contextmanager
    def listing_template(self, name: str, *more: str) -> Iterator[None]:
        """Hold the write lock for ``name``, and for each of ``more``, for
        the ``with`` block. Take it around the whole check-then-write.

        Several names, such as a rename's old and new, are taken in one sorted
        order, so two callers naming the same pair cannot each hold one and
        wait for the other. Names are compared case-insensitively, as Windows
        compares the directory names they become.
        """
        keys = sorted({key.casefold() for key in (name, *more)})
        with ExitStack() as stack:
            for key in keys:
                stack.enter_context(self._lock(key))
            yield

    def _lock(self, key: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())
