"""A locked least-recently-used cache bounded by total size.

Every in-process cache of decoded arrays has the same needs: a budget in bytes
rather than entries (one full-size design array is worth fifty editor-scale
bases), thread safety (FastAPI runs ``def`` endpoints on a thread pool, and
preparation runs beside it), and one rule for an item bigger than the whole
budget -- it is served without being kept, since keeping it would evict
everything and then itself. ``cachetools.LRUCache`` does the eviction and the
size accounting; it is not thread-safe, so every access here holds a lock. The
lock covers bookkeeping only, never ``compute()``: decoding under a mutex would
serialise exactly the requests a cache exists to make cheap.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Hashable

from cachetools import LRUCache


class BoundedCache[K: Hashable, V]:
    """At most ``budget`` units of ``size(value)`` (bytes, typically), the
    least recently read or written evicted first. Without ``size`` every entry
    counts 1, which makes ``budget`` an entry count."""

    def __init__(self, budget: int, size: Callable[[V], int] | None = None) -> None:
        self._entries: LRUCache[K, V] = LRUCache(budget, getsizeof=size)
        self._lock = threading.Lock()

    def get(self, key: K) -> V | None:
        """The kept value, now the most recently used; ``None`` when absent."""
        with self._lock:
            return self._entries.get(key)

    def put(self, key: K, value: V) -> None:
        """Keep ``value``, replacing ``key``'s old value. An oversized value
        still drops the old one, so a reader never gets the superseded value,
        and evicts nothing else."""
        with self._lock:
            self._store(key, value)

    def get_or_compute(self, key: K, compute: Callable[[], V]) -> V:
        """The kept value, or ``compute()``'s, kept before it is returned.

        Two threads missing the same key at once each compute; the first to
        store wins and both return its value, so every caller holds the same
        object and the accounting counts it once."""
        cached = self.get(key)
        if cached is not None:
            return cached
        value = compute()
        with self._lock:
            raced = self._entries.get(key)
            if raced is not None:
                return raced
            self._store(key, value)
        return value

    def _store(self, key: K, value: V) -> None:
        self._entries.pop(key, None)
        try:
            self._entries[key] = value
        except ValueError:
            # cachetools refuses an item over the whole budget before touching
            # anything; any other ValueError (a negative size) is a bug.
            if self._entries.getsizeof(value) <= self._entries.maxsize:
                raise

    def discard(self, key: K) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    @property
    def held(self) -> int:
        """Total ``size`` of what is kept."""
        with self._lock:
            return int(self._entries.currsize)
