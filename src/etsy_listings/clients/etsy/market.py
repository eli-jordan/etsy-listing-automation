"""Reading the Etsy market: other sellers' active listings, their stats, and
their review counts (market-seo.md, *Search* and *Stats*).

Three calls, each the one the spec names and nothing more -- the filtering,
scoring and rationing that decide *which* calls to make live in research, not
here:

- :meth:`~EtsyMarketClient.search_active`: `findAllListingsActive`, ranked by
  Etsy's own relevance for a US buyer, with no ``taxonomy_id`` (the item type
  at the end of each query does that job).
- :meth:`~EtsyMarketClient.listings_by_ids`: `getListingsByListingIds` with
  the shop and images attached, a hundred ids a call.
- :meth:`~EtsyMarketClient.review_count`: `getReviewsByListing`, one review
  asked for and only its total read.

Read-only by type, like :mod:`shops`: a caller holding an
:class:`EtsyMarketClient` cannot reach a write however the transport underneath
is shared (A22). All three calls are unscoped -- the app key pair is enough --
so the client needs no sign-in (see ``connections.etsy_market_client``).

Pacing and retries are the transport's: header pacing through
:class:`~etsy_listings.clients.etsy.transport.RateGate`, and the shared retry
policy for 429, 5xx and network errors. What surfaces here after those is a
failure research reports as *Etsy market search failed*.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Protocol

from etsy_listings.clients.etsy.models import MarketCandidate, MarketListing
from etsy_listings.clients.etsy.transport import HTTP_NOT_FOUND, EtsyApiError, Transport

SEARCH_PATH = "/v3/application/listings/active"
BATCH_PATH = "/v3/application/listings/batch"

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
        """Active listings matching ``query``, in the order Etsy ranks them
        for a buyer (``sort_on=score``) who ships to the US -- the country the
        seo prompt writes for. Deliberately no ``taxonomy_id``: nothing in a
        listing or garment profile records one (market-seo.md, *Search*)."""
        response = self._transport.get(
            SEARCH_PATH,
            params={
                "keywords": query,
                "sort_on": "score",
                "limit": limit,
                "buyer_country": "US",
            },
        )
        return [MarketCandidate.model_validate(row) for row in _results(response.json())]

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
        return [MarketListing.model_validate(row) for row in _results(response.json())]

    def review_count(self, listing_id: int) -> int:
        """How many reviews the listing has: the nearest thing to per-listing
        sales the API offers, and the one per-listing call, so the one
        research rations (market-seo.md, *Stats*).

        ``limit=1`` because ``count`` is the total whatever the page size
        (measured). A listing gone since the batch counts zero rather than
        failing the run; a body with no ``count`` is refused, since zero
        there would be a guess scored as evidence.
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


def _results(body: Any) -> list[Any]:
    """Etsy's list envelope is always ``{count, results}``."""
    if isinstance(body, dict) and isinstance(body.get("results"), list):
        return list(body["results"])
    return []


def _missing_ids(error: EtsyApiError) -> set[int] | None:
    """The ids a batch ``404`` names as gone, or ``None`` for any other
    failure -- only the one measured shape is read as "some ids are gone"."""
    if error.status_code != HTTP_NOT_FOUND:
        return None
    match = _MISSING_IDS.search(error.error)
    if match is None:
        return None
    return {int(part) for part in re.findall(r"\d+", match.group(1))}
