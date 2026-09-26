"""The 7-day market caches (market-seo.md, *Cache*), wrapping any
:class:`~etsy_listings.clients.etsy.market.EtsyMarketClient` the way
``clients/printify/cache.py`` wraps a catalog client.

Two caches, both under ``.cache/market/`` (gitignored, fully derivable --
PRD 22):

- **search** -- one file per query *and* search parameters, since the same
  words asked with another page size or sort order are a different answer;
- **stats** -- one file per ``listing_id``, holding the batch fields and the
  review count, each with its own fetch time because research asks for them
  at different moments and for different sets of listings.

Similar queries return largely the same listings, so the stats cache is the
one that absorbs most of a repeat run's calls even when extraction words the
queries differently (market-seo.md, *Cache*).

Research calls from five threads at once. Every read and write of a cache
file goes through one process-wide lock, and every write replaces its file
whole, so no reader sees half a file and no two read-modify-writes of one
listing's stats interleave. Etsy calls are made *outside* the lock.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from etsy_listings.clients.etsy.market import EtsyMarketClient, search_params
from etsy_listings.clients.etsy.models import ALREADY_DECODED, MarketCandidate, MarketListing
from etsy_listings.workspace.workspace import Workspace

DEFAULT_TTL = timedelta(days=7)

CACHE_SCHEMA = 1
"""Bumped whenever a cached shape changes, so an entry an older build wrote is
refetched rather than decoded into something wrong (the Printify cache's
rule)."""

_CANDIDATES = TypeAdapter(list[MarketCandidate])

_IO_LOCK = threading.Lock()
"""Process-wide rather than per instance: each AI run may build its own
client over the same directories."""


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
        """``inner`` cached under the workspace's ``.cache/market/``."""
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
            _write(
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
        about those with no live entry. A listing Etsy left out of its answer
        is gone (deactivated since the search) and is remembered as gone for
        the same seven days, so a repeat run does not ask about it again."""
        wanted = list(dict.fromkeys(ids))
        known: dict[int, MarketListing | None] = {}
        with _IO_LOCK:
            for listing_id in wanted:
                entry = self._stats_entry(listing_id).get("listing")
                if isinstance(entry, dict) and self._live(entry):
                    with contextlib.suppress(ValidationError):
                        known[listing_id] = _decoded_listing(entry.get("data"))
        missing = [listing_id for listing_id in wanted if listing_id not in known]
        if missing:
            fetched = {
                listing.listing_id: listing for listing in self._inner.listings_by_ids(missing)
            }
            now = self._clock()
            with _IO_LOCK:
                for listing_id in missing:
                    listing = fetched.get(listing_id)
                    data = None if listing is None else listing.model_dump(mode="json")
                    self._update_stats(listing_id, "listing", {"fetched_at": now, "data": data})
                    known[listing_id] = listing
        return [listing for listing_id in ids if (listing := known.get(listing_id)) is not None]

    def review_count(self, listing_id: int) -> int:
        with _IO_LOCK:
            entry = self._stats_entry(listing_id).get("reviews")
        if isinstance(entry, dict) and self._live(entry) and isinstance(entry.get("data"), int):
            count: int = entry["data"]
            return count
        count = self._inner.review_count(listing_id)
        with _IO_LOCK:
            self._update_stats(listing_id, "reviews", {"fetched_at": self._clock(), "data": count})
        return count

    def _stats_path(self, listing_id: int) -> Path:
        return self._stats_dir / f"{listing_id}.json"

    def _stats_entry(self, listing_id: int) -> dict[str, Any]:
        """One listing's stats file: ``listing`` (the batch fields, or
        ``None`` for gone) and ``reviews``, each ``{fetched_at, data}``.
        Called under :data:`_IO_LOCK`."""
        return _read(self._stats_path(listing_id)) or {}

    def _update_stats(self, listing_id: int, part: str, value: dict[str, Any]) -> None:
        """Replace one part of a listing's stats, keeping the other. Called
        under :data:`_IO_LOCK`, which is what keeps a batch and a review
        count for the same listing from overwriting each other."""
        entry = self._stats_entry(listing_id)
        entry.update({"schema": CACHE_SCHEMA, part: value})
        _write(self._stats_path(listing_id), entry)

    def _live(self, entry: dict[str, Any]) -> bool:
        fetched_at = entry.get("fetched_at")
        return isinstance(fetched_at, int | float) and (
            self._clock() - fetched_at < self._ttl_seconds
        )


def _decoded_listing(data: Any) -> MarketListing | None:  # noqa: ANN401 - JSON
    """A cached listing, or ``None`` when it was recorded as gone."""
    if data is None:
        return None
    return MarketListing.model_validate(data, context=ALREADY_DECODED)


def _key(params: dict[str, str | int]) -> str:
    """The file name for one search: a digest of every parameter, so any
    change to what would be sent is a different entry."""
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _read(path: Path) -> dict[str, Any] | None:
    """The entry at ``path``, or ``None`` for a missing, unreadable or
    older-schema file: the cache is derivable, so anything doubtful is a
    miss rather than an error."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != CACHE_SCHEMA:
        return None
    return payload


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(temporary, path)
