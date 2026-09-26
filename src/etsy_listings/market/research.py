"""Three buyer queries in, twenty scored comparable listings out
(market-seo.md, *Market search* and *Scoring*).

The order of work is the order of cost. Searches and the batch are cheap and
fixed -- three and one -- so every candidate gets them. The review count is
the only per-listing call, so it is rationed: the candidates are ranked first
on the free signals, and only the top twenty are asked. With an empty cache a
research run therefore makes at most 3 + 1 + 20 calls.

Calls go out at most :data:`MAX_IN_FLIGHT` at a time; pacing and retries are
the transport's. A call that still fails after those fails the whole run
(:class:`MarketResearchError`): the market data is the primary driver of the
proposal's wording, so there is no quietly carrying on without it.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

import httpx

from etsy_listings.clients.etsy.market import EtsyMarketClient
from etsy_listings.clients.etsy.models import MarketCandidate, MarketListing
from etsy_listings.errors import UserFacingError
from etsy_listings.market.block import lead
from etsy_listings.market.models import (
    MarketResult,
    MarketWeights,
    Metric,
    ScoredListing,
)
from etsy_listings.market.phrases import rank_phrases
from etsy_listings.market.scoring import display_score, rescaled, weighted

SEARCH_LIMIT = 25
"""Results per query: 3 x 25 gives about sixty unique candidates."""

MAX_IN_FLIGHT = 5
"""Etsy calls one research run has open at once (market-seo.md, *Quota*)."""

SCORED = 20
"""How many listings get a review count, and so a final score."""

MIN_AGE_DAYS = 30
"""A younger listing's per-day rates are too noisy to score."""

_DAY = 86_400


class MarketResearchError(UserFacingError):
    """An Etsy call failed after the transport's retries. The message is the
    spec's, *Etsy market search failed: <reason>*, so a seller can tell an
    Etsy problem from a model one."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Etsy market search failed: {reason}")


class ResearchCancelled(Exception):
    """The run's cancel event was set. Raised at the next boundary between
    calls; calls already in flight finish, and nothing new starts."""


class _Aborted(Exception):
    """A sibling call failed first; this one never started."""


@dataclass(frozen=True)
class _Candidate:
    listing: MarketListing
    search_rank: int


def research(
    queries: Sequence[str],
    client: EtsyMarketClient,
    *,
    today: datetime,
    weights: MarketWeights | None = None,
    own_shop_id: int | None = None,
    cancel_event: threading.Event | None = None,
) -> MarketResult:
    """Search, filter, rank on the free signals, count reviews for the top
    twenty, score them, and list their phrases.

    ``today`` is the moment listing ages are measured from. ``own_shop_id``
    is ``shop.yaml``'s ``etsy.shop_id``; a listing from it is marked, never
    excluded. ``cancel_event`` is checked before every call.

    Raises :class:`MarketResearchError` when an Etsy call fails, and
    :class:`ResearchCancelled` when ``cancel_event`` is set.
    """
    calls = _Calls(cancel_event or threading.Event())
    weights = weights or MarketWeights()
    queries = tuple(queries)

    searches = calls.each(lambda query: client.search_active(query, limit=SEARCH_LIMIT), queries)
    found = _merge(searches)

    now = today.timestamp()
    old_enough = [
        candidate
        for candidate in found
        if (age := _age_days(candidate[0], now)) is not None and age >= MIN_AGE_DAYS
    ]
    # Relaxing (market-seo.md, *Filters*): the age filter is the only one
    # research applies itself, so dropping it is a second pass over what was
    # already found -- a new search would return the same listings.
    relaxed = not old_enough
    survivors = old_enough or found
    if not survivors:
        return _empty(queries, len(found), relaxed=relaxed)

    ranks = {candidate.listing_id: rank for candidate, rank in survivors}
    stats = calls.one(lambda: client.listings_by_ids([c.listing_id for c, _ in survivors]))
    candidates = [
        _Candidate(listing, ranks[listing.listing_id])
        for listing in stats
        if listing.listing_id in ranks
    ]
    if not candidates:
        return _empty(queries, len(found), relaxed=relaxed)

    preliminary = _order(candidates, rescaled(weights, exclude={"reviews"}), now, reviews=None)
    top = [candidate for candidate, _ in preliminary[:SCORED]]

    counts = calls.each(lambda c: client.review_count(c.listing.listing_id), top)
    final = _order(top, rescaled(weights), now, reviews=counts)
    review_of = {c.listing.listing_id: n for c, n in zip(top, counts, strict=True)}

    listings = tuple(
        _scored(candidate, rank, score, review_of[candidate.listing.listing_id], now, own_shop_id)
        for rank, (candidate, score) in enumerate(final, start=1)
    )
    return MarketResult(
        queries=queries,
        found=len(found),
        scored=len(listings),
        listings=listings,
        phrases=rank_phrases(listings),
        relaxed=relaxed,
        empty=False,
    )


# ------------------------------------------------------------------ calls


class _Calls:
    """Every Etsy call research makes goes through here: at most
    :data:`MAX_IN_FLIGHT` at once, the cancel event checked before each, and
    the failures turned into the one error research raises.

    One failed call stops the rest from *starting* -- the run has failed, so
    anything more is quota spent on an answer nobody reads.
    """

    def __init__(self, cancel: threading.Event) -> None:
        self._cancel = cancel
        self._abort = threading.Event()

    def one[T](self, call: Callable[[], T]) -> T:
        return self._guarded(call)

    def each[A, T](self, call: Callable[[A], T], arguments: Iterable[A]) -> list[T]:
        with ThreadPoolExecutor(max_workers=MAX_IN_FLIGHT) as pool:
            futures = [
                pool.submit(self._guarded, lambda a=argument: call(a)) for argument in arguments
            ]
        errors = [error for f in futures if (error := f.exception()) is not None]
        self._check_cancel()
        real = [error for error in errors if not isinstance(error, _Aborted)]
        if real:
            raise real[0]
        return [future.result() for future in futures]

    def _guarded[T](self, call: Callable[[], T]) -> T:
        self._check_cancel()
        if self._abort.is_set():
            raise _Aborted
        try:
            return call()
        except UserFacingError as exc:
            self._abort.set()
            raise MarketResearchError(str(exc)) from exc
        except httpx.HTTPError as exc:
            self._abort.set()
            raise MarketResearchError(str(exc) or type(exc).__name__) from exc

    def _check_cancel(self) -> None:
        if self._cancel.is_set():
            raise ResearchCancelled


# -------------------------------------------------------------- the pipeline


def _merge(searches: Sequence[Sequence[MarketCandidate]]) -> list[tuple[MarketCandidate, int]]:
    """Every candidate once, with its best (lowest) 1-based position across
    the queries, best first -- ties by id, so the order is the same whichever
    query answered first."""
    best: dict[int, tuple[MarketCandidate, int]] = {}
    for results in searches:
        for position, candidate in enumerate(results, start=1):
            known = best.get(candidate.listing_id)
            if known is None or position < known[1]:
                best[candidate.listing_id] = (candidate, position)
    return sorted(best.values(), key=lambda pair: (pair[1], pair[0].listing_id))


def _age_days(listing: MarketCandidate, now: float) -> float | None:
    created = listing.original_creation_timestamp
    return None if created is None else (now - created) / _DAY


def _per_day(count: int, listing: MarketCandidate, now: float) -> float | None:
    """A count over the listing's age. Under a day old (only reachable once
    the age filter is relaxed) counts as one day, rather than turning a
    handful of favourites into a rate that tops the set. An unknown age has
    no rate, which scores lowest."""
    age = _age_days(listing, now)
    return None if age is None else count / max(age, 1.0)


def _order(
    candidates: Sequence[_Candidate],
    weights: dict[Metric, float],
    now: float,
    *,
    reviews: Sequence[int] | None,
) -> list[tuple[_Candidate, float]]:
    """The candidates with their 0-1 scores, best first. A tie keeps the
    better search position -- Etsy's own relevance is the fairest tie-break
    -- and then the lower id, so the order never depends on thread timing."""
    shops = [candidate.listing.shop for candidate in candidates]
    metrics: dict[Metric, Sequence[float | None]] = {
        "reviews": list(reviews) if reviews is not None else [0.0] * len(candidates),
        "favourites_per_day": [
            _per_day(c.listing.num_favorers, c.listing, now) for c in candidates
        ],
        # Inverted: 1st is best, and percentiles rank a higher value higher.
        "search_rank": [-c.search_rank for c in candidates],
        "views_per_day": [_per_day(c.listing.views, c.listing, now) for c in candidates],
        "shop_sales": [shop.transaction_sold_count if shop else 0 for shop in shops],
        "shop_rating": [shop.review_average if shop else None for shop in shops],
    }
    scores = weighted(metrics, weights)
    paired = list(zip(candidates, scores, strict=True))
    paired.sort(key=lambda pair: (-pair[1], pair[0].search_rank, pair[0].listing.listing_id))
    return paired


def _scored(
    candidate: _Candidate,
    rank: int,
    score: float,
    reviews: int,
    now: float,
    own_shop_id: int | None,
) -> ScoredListing:
    listing = candidate.listing
    shop = listing.shop
    return ScoredListing(
        listing_id=listing.listing_id,
        rank=rank,
        score_raw=score,
        score=display_score(score),
        title=listing.title,
        url=listing.url,
        shop_id=listing.shop_id,
        shop_name=shop.shop_name if shop else "",
        own_shop=own_shop_id is not None and listing.shop_id == own_shop_id,
        thumbnail_url=listing.thumbnail_url,
        search_rank=candidate.search_rank,
        reviews=reviews,
        favourites_per_day=_per_day(listing.num_favorers, listing, now),
        views_per_day=_per_day(listing.views, listing, now),
        shop_sales=shop.transaction_sold_count if shop else 0,
        shop_rating=shop.review_average if shop else None,
        tags=listing.tags,
        lead=lead(listing.description),
    )


def _empty(queries: tuple[str, ...], found: int, *, relaxed: bool) -> MarketResult:
    """Nothing comparable: the one outcome that lets the proposal go ahead
    without market data, since the calls worked and there was simply
    nothing to learn from (market-seo.md, *Filters*)."""
    return MarketResult(
        queries=queries,
        found=found,
        scored=0,
        listings=(),
        phrases=(),
        relaxed=relaxed,
        empty=True,
    )
