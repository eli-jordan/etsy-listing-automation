"""A locked least-recently-used cache bounded by total size.

``cachetools.LRUCache`` is not thread-safe, so every access here holds a lock.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Hashable

from cachetools import LRUCache


class BoundedCache[K: Hashable, V]:
    def __init__(self, budget: int, size: Callable[[V], int] | None = None) -> None:
        self._entries: LRUCache[K, V] = LRUCache(budget, getsizeof=size)
        self._lock = threading.Lock()

    def get(self, key: K) -> V | None:
        with self._lock:
            return self._entries.get(key)

    def put(self, key: K, value: V) -> None:
        with self._lock:
            self._store(key, value)

    def get_or_compute(self, key: K, compute: Callable[[], V]) -> V:
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
            # cachetools raises ValueError, untouched, for an item over the budget.
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
        with self._lock:
            return int(self._entries.currsize)
