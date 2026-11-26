"""The 7-day market caches (features/market-seo-20260924/spec.md, *Cache*), wrapping any
:class:`~etsy_listings.core.clients.etsy.market.EtsyMarketClient` the way
``clients/printify/cache.py`` wraps a catalog client.

Research calls from several threads at once. Every cache file read and
write holds one process-wide lock and replaces the file whole, so no reader
sees half a file and no two read-modify-writes of one listing's stats
interleave. Etsy calls are made *outside* the lock.
"""

from __future__ import annotations

import contextlib
import enum
import hashlib
import json
import threading
import time
from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import JsonValue, TypeAdapter, ValidationError

from etsy_listings.core.clients.etsy.market import EtsyMarketClient, search_params
from etsy_listings.core.clients.etsy.models import ALREADY_DECODED, MarketCandidate, MarketListing
from etsy_listings.core.workspace.atomic import write_json_atomic
from etsy_listings.core.workspace.workspace import Workspace

DEFAULT_TTL = timedelta(days=7)

CACHE_SCHEMA = 1
"""Bumped whenever a cached shape changes, so an entry an older build wrote is
refetched rather than decoded into something wrong (the Printify cache's
rule)."""

_CANDIDATES = TypeAdapter(list[MarketCandidate])

_IO_LOCK = threading.Lock()
"""Process-wide rather than per instance: each AI run may build its own
client over the same directories."""


class _Gone(enum.Enum):
    GONE = enum.auto()


_GONE: Final = _Gone.GONE

_StatsPart = Literal["listing", "reviews"]


class CachedEtsyMarketClient:
    def __init__(
        self,
        inner: EtsyMarketClient,
        *,
        search_dir: Path,
        stats_dir: Path,
        ttl: timedelta = DEFAULT_TTL,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._inner = inner
        self._search_dir = search_dir
        self._stats_dir = stats_dir
        self._ttl_seconds = ttl.total_seconds()
        self._clock = clock

    @classmethod
    def in_workspace(cls, inner: EtsyMarketClient, workspace: Workspace) -> CachedEtsyMarketClient:
        return cls(
            inner,
            search_dir=workspace.market_search_cache_dir(),
            stats_dir=workspace.market_stats_cache_dir(),
        )

    def search_active(self, query: str, *, limit: int = 25) -> list[MarketCandidate]:
        params = search_params(query, limit=limit)
        path = self._search_dir / f"{_key(params)}.json"
        with _IO_LOCK:
            entry = _read(path)
        if entry is not None and entry.get("params") == params and self._live(entry):
            try:
                return _CANDIDATES.validate_python(entry["data"], context=ALREADY_DECODED)
            except ValidationError:
                pass
        found = self._inner.search_active(query, limit=limit)
        with _IO_LOCK:
            write_json_atomic(
                path,
                {
                    "schema": CACHE_SCHEMA,
                    "fetched_at": self._clock(),
                    "params": params,
                    "data": _CANDIDATES.dump_python(found, mode="json"),
                },
            )
        return found

    def listings_by_ids(self, ids: Sequence[int]) -> list[MarketListing]:
        """Each listing's batch fields, in the order asked, asking Etsy only
        about those with no live entry; one Etsy left out is cached as gone."""
        wanted = list(dict.fromkeys(ids))
        known = self._cached_listings(wanted)
        missing = [listing_id for listing_id in wanted if listing_id not in known]
        if missing:
            known |= self._fetch_listings(missing)
        return [
            listing
            for listing_id in ids
            if isinstance(listing := known.get(listing_id), MarketListing)
        ]

    def _cached_listings(self, wanted: list[int]) -> dict[int, MarketListing | _Gone]:
        known: dict[int, MarketListing | _Gone] = {}
        with _IO_LOCK:
            for listing_id in wanted:
                entry = self._stats_entry_locked(listing_id).get("listing")
                if isinstance(entry, dict) and self._live(entry):
                    with contextlib.suppress(ValidationError):
                        known[listing_id] = _decoded_listing(entry.get("data"))
        return known

    def _fetch_listings(self, missing: list[int]) -> dict[int, MarketListing | _Gone]:
        fetched = {listing.listing_id: listing for listing in self._inner.listings_by_ids(missing)}
        now = self._clock()
        known: dict[int, MarketListing | _Gone] = {}
        with _IO_LOCK:
            for listing_id in missing:
                listing = fetched.get(listing_id)
                data = None if listing is None else listing.model_dump(mode="json")
                self._update_stats_locked(listing_id, "listing", {"fetched_at": now, "data": data})
                known[listing_id] = _GONE if listing is None else listing
        return known

    def review_count(self, listing_id: int) -> int:
        with _IO_LOCK:
            entry = self._stats_entry_locked(listing_id).get("reviews")
        if isinstance(entry, dict) and self._live(entry) and isinstance(entry.get("data"), int):
            count: int = entry["data"]
            return count
        count = self._inner.review_count(listing_id)
        with _IO_LOCK:
            self._update_stats_locked(
                listing_id, "reviews", {"fetched_at": self._clock(), "data": count}
            )
        return count

    def _stats_path(self, listing_id: int) -> Path:
        return self._stats_dir / f"{listing_id}.json"

    def _stats_entry_locked(self, listing_id: int) -> dict[str, Any]:
        """One listing's stats file: ``listing`` (the batch fields, or
        ``None`` for gone) and ``reviews``, each ``{fetched_at, data}``."""
        assert _IO_LOCK.locked()
        return _read(self._stats_path(listing_id)) or {}

    def _update_stats_locked(
        self, listing_id: int, part: _StatsPart, value: dict[str, Any]
    ) -> None:
        entry = self._stats_entry_locked(listing_id)
        entry.update({"schema": CACHE_SCHEMA, part: value})
        write_json_atomic(self._stats_path(listing_id), entry)

    def _live(self, entry: dict[str, Any]) -> bool:
        fetched_at = entry.get("fetched_at")
        return isinstance(fetched_at, int | float) and (
            self._clock() - fetched_at < self._ttl_seconds
        )


def _decoded_listing(data: JsonValue) -> MarketListing | _Gone:
    if data is None:
        return _GONE
    return MarketListing.model_validate(data, context=ALREADY_DECODED)


def _key(params: dict[str, str | int]) -> str:
    """The file name for one search: a digest of every parameter sent."""
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _read(path: Path) -> dict[str, Any] | None:
    """The entry at ``path``, or ``None`` for a missing, unreadable or
    older-schema file."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != CACHE_SCHEMA:
        return None
    return payload
