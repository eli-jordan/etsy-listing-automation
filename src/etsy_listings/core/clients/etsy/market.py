"""Reading the Etsy market: other sellers' active listings, their stats, and
their review counts."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Protocol

from etsy_listings.core.clients.etsy.models import MarketCandidate, MarketListing
from etsy_listings.core.clients.etsy.transport import (
    HTTP_NOT_FOUND,
    EtsyApiError,
    Transport,
    results_of,
)

SEARCH_PATH = "/v3/application/listings/active"
BATCH_PATH = "/v3/application/listings/batch"

SEARCH_DEFAULTS: dict[str, str] = {"sort_on": "score", "buyer_country": "US"}
"""Every `findAllListingsActive` parameter besides the query and the page
size. One definition, read by :func:`search_params` -- and so by both the
request and the search cache's key, which must change whenever a request
would."""

BATCH_LIMIT = 100
"""Etsy's documented ceiling on `getListingsByListingIds`. About sixty
candidates survive three searches, so one call normally covers them all."""

_MISSING_IDS = re.compile(r"Missing listing_ids:\s*([\d,\s]+)")


class EtsyMarketClient(Protocol):
    """What market research asks Etsy. Reads only, and safe to call from
    several threads at once -- research keeps up to five calls in flight."""

    def search_active(self, query: str, *, limit: int = 25) -> list[MarketCandidate]: ...

    def listings_by_ids(self, ids: Sequence[int]) -> list[MarketListing]: ...

    def review_count(self, listing_id: int) -> int: ...


class HttpEtsyMarketClient:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def search_active(self, query: str, *, limit: int = 25) -> list[MarketCandidate]:
        response = self._transport.get(SEARCH_PATH, params=search_params(query, limit=limit))
        return [MarketCandidate.model_validate(row) for row in results_of(response.json())]

    def listings_by_ids(self, ids: Sequence[int]) -> list[MarketListing]:
        """Each listing's stats, shop and thumbnail, in chunks of
        :data:`BATCH_LIMIT`.

        An id Etsy no longer has is **absent** from the answer. Etsy refuses
        the whole chunk with a ``404`` naming the missing ids (measured), and
        a listing deactivated between the search and this call is ordinary --
        so the chunk is asked again without them, once.
        """
        listings: list[MarketListing] = []
        wanted = list(ids)
        for start in range(0, len(wanted), BATCH_LIMIT):
            listings.extend(self._batch(wanted[start : start + BATCH_LIMIT]))
        return listings

    def _batch(self, chunk: list[int]) -> list[MarketListing]:
        try:
            return self._fetch_batch(chunk)
        except EtsyApiError as exc:
            missing = _missing_ids(exc)
            if missing is None:
                raise
        remaining = [listing_id for listing_id in chunk if listing_id not in missing]
        return self._fetch_batch(remaining) if remaining else []

    def _fetch_batch(self, chunk: list[int]) -> list[MarketListing]:
        response = self._transport.get(
            BATCH_PATH,
            params={
                "listing_ids": ",".join(str(listing_id) for listing_id in chunk),
                "includes": "Shop,Images",
            },
        )
        return [MarketListing.model_validate(row) for row in results_of(response.json())]

    def review_count(self, listing_id: int) -> int:
        """A listing gone since the batch counts zero rather than failing the
        run; a body with no ``count`` is refused, since zero there would be a
        guess scored as evidence.
        """
        try:
            response = self._transport.get(
                f"/v3/application/listings/{listing_id}/reviews", params={"limit": 1}
            )
        except EtsyApiError as exc:
            if exc.status_code == HTTP_NOT_FOUND:
                return 0
            raise
        body: Any = response.json()
        count = body.get("count") if isinstance(body, dict) else None
        if not isinstance(count, int):
            raise EtsyApiError(
                response.status_code, error=f"reviews for listing {listing_id} had no count"
            )
        return count


def search_params(query: str, *, limit: int) -> dict[str, str | int]:
    return {"keywords": query, "limit": limit, **SEARCH_DEFAULTS}


def _missing_ids(error: EtsyApiError) -> set[int] | None:
    """The ids a batch ``404`` names as gone, or ``None`` for any other
    failure -- only the one measured shape is read as "some ids are gone"."""
    if error.status_code != HTTP_NOT_FOUND:
        return None
    match = _MISSING_IDS.search(error.error)
    if match is None:
        return None
    return {int(part) for part in re.findall(r"\d+", match.group(1))}
