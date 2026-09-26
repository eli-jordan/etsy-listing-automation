"""Per-listing write locks for the UI process (market-seo implementation
plan, PR 3).

Every write the UI makes to a listing is **read, merge, write**: PATCH reads
``listing.yaml``, merges the editor's slice into it and writes the whole
document back; ``DELETE`` does the same to set ``lifecycle: deleted``; an AI
run's brief write (PR 5) re-reads the listing to check the brief is still
empty before writing it. Two of those interleaved -- both read, then both
write -- and the first write is lost without a trace: the second wrote a
document merged over what the file said *before* the first. Autosave makes
that ordinary rather than rare, since the editor fires a PATCH per field as
the seller moves between them, and a run writes in the background.

Rename and create take the same locks for the same reason one level up:
each checks a name is free (or still there) and then moves or writes, and a
write that waited on a rename must find the listing gone rather than
recreate it under its old name.

The locks are in memory and per process, which is enough: the UI server is
the only writer of ``listing.yaml`` while it runs. They do not cover the CLI
running against the same workspace at the same time, which nothing in the
tool has ever guarded.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager


class WorkspaceLocks:
    """One lock per listing name, made on first use and kept for the
    process's life (a lock per listing a seller has ever touched is a few
    hundred bytes)."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    @contextmanager
    def listing(self, name: str, *more: str) -> Iterator[None]:
        """Hold the write lock for ``name`` (and each of ``more``) for the
        ``with`` block.

        Take it around the whole read-merge-write, and re-check the listing
        still exists *inside* it: a rename may have moved it while this
        caller waited. Several names -- a rename's old and new -- are taken
        in one sorted order, so two callers naming the same pair cannot each
        hold one and wait for the other.

        Names are compared case-insensitively, as Windows compares the
        directory names they become.
        """
        keys = sorted({key.casefold() for key in (name, *more)})
        with ExitStack() as stack:
            for key in keys:
                stack.enter_context(self._lock(key))
            yield

    def _lock(self, key: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())
