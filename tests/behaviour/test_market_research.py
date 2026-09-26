"""Market research end to end against the in-memory Etsy market
(market-seo.md, *Market search* and *Scoring*; implementation plan, PR 2).

Three queries in; out come at most twenty scored listings, a phrase list and
the counts the panel shows. What these tests hold research to is mostly about
*calls*, since calls are quota: at most 3 + 1 + 20 with an empty cache, the
review count -- the one per-listing call -- only for the preliminary top
twenty, never more than five in flight, and none after a cancel.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from etsy_listings.clients.etsy.fakes import (
    FakeEtsyMarketClient,
    market_listing,
    network_error,
    server_error,
)
from etsy_listings.clients.etsy.models import MarketCandidate, MarketListing, ShopStats
from etsy_listings.market import (
    MarketResearchError,
    MarketWeights,
    ResearchCancelled,
    research,
)

TODAY = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
DAY = 86_400
QUERIES = ("retro sunset hiking shirt", "mountain sunset tee", "hiking gift shirt")


def _days_ago(days: float) -> int:
    return int(TODAY.timestamp() - days * DAY)


def _seed(fake: FakeEtsyMarketClient, listing_id: int, *, reviews: int = 0, **fields: Any) -> None:
    fields.setdefault("original_creation_timestamp", _days_ago(100))
    fake.seed_listing(market_listing(listing_id, **fields), reviews=reviews)


def _run(fake: FakeEtsyMarketClient, **kwargs: Any):  # noqa: ANN202 - MarketResult
    kwargs.setdefault("today", TODAY)
    return research(QUERIES, fake, **kwargs)


# ---------------------------------------------------------------- scoring


def _three_listings() -> FakeEtsyMarketClient:
    """Worked by hand from the spec's table (percentiles 0, 0.5, 1 in a
    set of three; default weights 30/30/20/10/5/5):

    ======== ======= ======= ====== ======= ===== ====== =====
    listing  reviews fav/day rank   views/d sales rating score
    ======== ======= ======= ====== ======= ===== ====== =====
    1        10 .5   3 1     1st 1  10 0    50 .5 4.9 1  72.5
    2        40 1    1 0     2nd .5 30 1    500 1 4.5 .5 57.5
    3        0 0     2 .5    3rd 0  20 .5   5 0   none 0 20
    ======== ======= ======= ====== ======= ===== ====== =====
    """
    fake = FakeEtsyMarketClient()
    _seed(
        fake,
        1,
        reviews=10,
        num_favorers=300,
        views=1000,
        title="Retro Sunset Hiking Shirt",
        tags=("hiking shirt", "retro sunset"),
        description="A retro sunset over the peaks. Printed to order.",
        shop=ShopStats(shop_name="TrailTees", transaction_sold_count=50, review_average=4.9),
        thumbnail_url="https://img.test/1_170x135.jpg",
    )
    _seed(
        fake,
        2,
        reviews=40,
        num_favorers=100,
        views=3000,
        tags=("hiking shirt",),
        shop=ShopStats(shop_name="PeakPrints", transaction_sold_count=500, review_average=4.5),
    )
    _seed(
        fake,
        3,
        reviews=0,
        num_favorers=200,
        views=2000,
        tags=("camping tee",),
        shop=ShopStats(shop_name="NewShop", transaction_sold_count=5, review_average=None),
    )
    fake.seed_search(QUERIES[0], [1, 2, 3])
    return fake


def test_listings_are_scored_ranked_and_described_for_the_panel() -> None:
    result = _run(_three_listings(), own_shop_id=1002)

    assert [(row.listing_id, row.rank, row.score) for row in result.listings] == [
        (1, 1, 73),
        (2, 2, 58),
        (3, 3, 20),
    ]
    assert [row.score_raw for row in result.listings] == pytest.approx([0.725, 0.575, 0.2])
    first = result.listings[0]
    assert first.title == "Retro Sunset Hiking Shirt"
    assert first.shop_name == "TrailTees"
    assert first.shop_rating == 4.9
    assert first.shop_sales == 50
    assert first.reviews == 10
    assert first.favourites_per_day == pytest.approx(3.0)
    assert first.views_per_day == pytest.approx(10.0)
    assert first.search_rank == 1
    assert first.lead == "A retro sunset over the peaks."
    assert first.tags == ("hiking shirt", "retro sunset")
    assert first.thumbnail_url == "https://img.test/1_170x135.jpg"
    assert first.url == "https://www.etsy.test/listing/1"
    assert [row.own_shop for row in result.listings] == [False, True, False]
    assert (result.found, result.scored, result.relaxed, result.empty) == (3, 3, False, False)
    assert result.queries == QUERIES


def test_the_phrase_list_is_built_from_the_scored_listings() -> None:
    result = _run(_three_listings())
    # hiking shirt 0.725 + 0.575 = 1.3; retro sunset 0.725; camping tee 0.2.
    assert [(p.phrase, p.listings) for p in result.phrases] == [
        ("hiking shirt", 2),
        ("retro sunset", 1),
        ("camping tee", 1),
    ]
    assert [p.score for p in result.phrases] == pytest.approx([1.0, 0.725 / 1.3, 0.2 / 1.3])


def test_weights_change_the_order() -> None:
    only_reviews = MarketWeights(
        reviews=1,
        favourites_per_day=0,
        search_rank=0,
        views_per_day=0,
        shop_sales=0,
        shop_rating=0,
    )
    result = _run(_three_listings(), weights=only_reviews)
    assert [(row.listing_id, row.score) for row in result.listings] == [(2, 100), (1, 50), (3, 0)]


# ---------------------------------------------------- searching and merging


def test_a_listing_found_by_several_queries_keeps_its_best_position() -> None:
    fake = FakeEtsyMarketClient()
    for listing_id in range(1, 7):
        _seed(fake, listing_id)
    fake.seed_search(QUERIES[0], [1, 2, 3, 4, 5])
    fake.seed_search(QUERIES[1], [6, 5])
    fake.seed_search(QUERIES[2], [3])

    result = _run(fake)

    by_id = {row.listing_id: row.search_rank for row in result.listings}
    assert by_id == {1: 1, 2: 2, 3: 1, 4: 4, 5: 2, 6: 1}
    assert result.found == 6
    assert fake.count("listings_by_ids") == 1


def test_each_query_is_searched_once_for_twenty_five_results() -> None:
    fake = FakeEtsyMarketClient()
    for listing_id in range(1, 31):
        _seed(fake, listing_id)
    fake.seed_search(QUERIES[0], list(range(1, 31)))

    result = _run(fake)

    searched = sorted(call.argument for call in fake.calls if call.method == "search_active")
    assert searched == sorted(QUERIES)
    assert result.found == 25


def _thirty_graded_listings() -> FakeEtsyMarketClient:
    """Thirty listings where a lower id is better on every free signal, so
    the preliminary top twenty is ids 1-20 whatever the weights; and review
    counts that run the *other* way, so only the final score sees them."""
    fake = FakeEtsyMarketClient()
    for listing_id in range(1, 31):
        _seed(
            fake,
            listing_id,
            reviews=listing_id,
            num_favorers=1000 - listing_id,
            views=10_000 - listing_id,
            shop=ShopStats(
                transaction_sold_count=1000 - listing_id, review_average=5 - listing_id / 10
            ),
        )
    fake.seed_search(QUERIES[0], list(range(1, 26)))
    fake.seed_search(QUERIES[1], list(range(6, 31)))
    fake.seed_search(QUERIES[2], list(range(1, 11)))
    return fake


def test_review_counts_are_fetched_for_the_preliminary_top_twenty_only() -> None:
    fake = _thirty_graded_listings()

    result = _run(fake)

    reviewed = sorted(call.argument for call in fake.calls if call.method == "review_count")
    assert reviewed == list(range(1, 21))
    assert result.found == 30
    assert result.scored == 20
    assert sorted(row.listing_id for row in result.listings) == list(range(1, 21))


def test_a_full_research_makes_at_most_three_plus_one_plus_twenty_calls() -> None:
    fake = _thirty_graded_listings()
    _run(fake)
    assert (
        fake.count("search_active"),
        fake.count("listings_by_ids"),
        fake.count("review_count"),
    ) == (3, 1, 20)
    assert len(fake.calls) == 24


def test_the_batch_asks_for_every_surviving_candidate_best_first() -> None:
    fake = FakeEtsyMarketClient()
    for listing_id in (7, 8, 9):
        _seed(fake, listing_id)
    fake.seed_search(QUERIES[0], [9, 7])
    fake.seed_search(QUERIES[1], [8])
    _run(fake)
    batches = [call.argument for call in fake.calls if call.method == "listings_by_ids"]
    assert batches == [(8, 9, 7)]


# ------------------------------------------------------ age filter, relaxing


def test_listings_under_thirty_days_old_or_of_unknown_age_are_filtered_out() -> None:
    fake = FakeEtsyMarketClient()
    _seed(fake, 1, original_creation_timestamp=_days_ago(30))
    _seed(fake, 2, original_creation_timestamp=_days_ago(29.9))
    _seed(fake, 3, original_creation_timestamp=None)
    fake.seed_search(QUERIES[0], [1, 2, 3])

    result = _run(fake)

    assert [row.listing_id for row in result.listings] == [1]
    assert (result.found, result.scored, result.relaxed, result.empty) == (3, 1, False, False)
    assert [call.argument for call in fake.calls if call.method == "listings_by_ids"] == [(1,)]


def test_when_nothing_is_old_enough_the_age_filter_is_dropped_without_searching_again() -> None:
    fake = FakeEtsyMarketClient()
    _seed(fake, 1, original_creation_timestamp=_days_ago(10), num_favorers=50, views=100)
    _seed(fake, 2, original_creation_timestamp=_days_ago(0.25), num_favorers=5)
    _seed(fake, 3, original_creation_timestamp=None, num_favorers=500)
    fake.seed_search(QUERIES[0], [1, 2, 3])

    result = _run(fake)

    assert result.relaxed is True
    assert result.empty is False
    assert sorted(row.listing_id for row in result.listings) == [1, 2, 3]
    assert fake.count("search_active") == 3
    by_id = {row.listing_id: row for row in result.listings}
    assert by_id[1].favourites_per_day == pytest.approx(5.0)
    assert by_id[1].views_per_day == pytest.approx(10.0)
    # A listing under a day old is rated over one day, not a fraction of one.
    assert by_id[2].favourites_per_day == pytest.approx(5.0)
    # An unknown age has no per-day rate at all, and ranks lowest on both.
    assert by_id[3].favourites_per_day is None
    assert by_id[3].views_per_day is None


def test_nothing_found_is_an_empty_result_that_costs_only_the_searches() -> None:
    fake = FakeEtsyMarketClient()

    result = _run(fake)

    assert result.empty is True
    assert result.relaxed is True
    assert (result.found, result.scored, result.listings, result.phrases) == (0, 0, (), ())
    assert result.queries == QUERIES
    assert len(fake.calls) == 3


class _VanishingBatch(FakeEtsyMarketClient):
    """Every candidate deactivated between the search and the batch."""

    def listings_by_ids(self, ids: Sequence[int]) -> list[MarketListing]:
        super().listings_by_ids(ids)
        return []


def test_candidates_gone_by_the_batch_leave_an_empty_result() -> None:
    fake = _VanishingBatch()
    _seed(fake, 1)
    fake.seed_search(QUERIES[0], [1])

    result = _run(fake)

    assert result.empty is True
    assert (result.found, result.scored, result.relaxed) == (1, 0, False)
    assert fake.count("review_count") == 0


# ---------------------------------------------------------- cancellation


class _CancelDuring(FakeEtsyMarketClient):
    """Sets the cancel event from inside one of its calls, as a seller
    pressing Cancel mid-research would."""

    def __init__(self, method: str) -> None:
        super().__init__()
        self.cancel = threading.Event()
        self._method = method

    def search_active(self, query: str, *, limit: int = 25) -> list[MarketCandidate]:
        if self._method == "search_active":
            self.cancel.set()
        return super().search_active(query, limit=limit)

    def listings_by_ids(self, ids: Sequence[int]) -> list[MarketListing]:
        if self._method == "listings_by_ids":
            self.cancel.set()
        return super().listings_by_ids(ids)

    def review_count(self, listing_id: int) -> int:
        if self._method == "review_count":
            self.cancel.set()
            time.sleep(0.01)
        return super().review_count(listing_id)


def _graded_cancelling(method: str) -> _CancelDuring:
    fake = _CancelDuring(method)
    for listing_id in range(1, 31):
        _seed(fake, listing_id)
    fake.seed_search(QUERIES[0], list(range(1, 26)))
    fake.seed_search(QUERIES[1], list(range(6, 31)))
    return fake


def test_a_cancel_before_research_starts_makes_no_calls() -> None:
    fake = FakeEtsyMarketClient()
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ResearchCancelled):
        _run(fake, cancel_event=cancel)
    assert fake.calls == []


def test_a_cancel_during_the_searches_stops_before_the_batch() -> None:
    fake = _graded_cancelling("search_active")
    with pytest.raises(ResearchCancelled):
        _run(fake, cancel_event=fake.cancel)
    assert fake.count("listings_by_ids") == 0
    assert fake.count("review_count") == 0


def test_a_cancel_during_the_batch_stops_before_any_review_count() -> None:
    fake = _graded_cancelling("listings_by_ids")
    with pytest.raises(ResearchCancelled):
        _run(fake, cancel_event=fake.cancel)
    assert fake.count("review_count") == 0


def test_a_cancel_during_the_review_counts_starts_no_new_call() -> None:
    fake = _graded_cancelling("review_count")
    with pytest.raises(ResearchCancelled):
        _run(fake, cancel_event=fake.cancel)
    # Only the calls already in flight when the first one cancelled.
    assert 1 <= fake.count("review_count") <= 5


# ---------------------------------------------------------------- failures


@pytest.mark.parametrize(
    ("method", "error", "reason"),
    [
        (
            "search_active",
            server_error(),
            "Etsy refused the request with 503: upstream unavailable",
        ),
        (
            "listings_by_ids",
            server_error(502),
            "Etsy refused the request with 502: upstream unavailable",
        ),
        ("review_count", network_error(), "connection reset by peer"),
    ],
)
def test_a_failed_call_fails_research_with_the_spec_message(
    method: str, error: Exception, reason: str
) -> None:
    fake = _thirty_graded_listings()
    fake.fail(method, error)  # type: ignore[arg-type]

    with pytest.raises(MarketResearchError) as raised:
        _run(fake)

    assert str(raised.value) == f"Etsy market search failed: {reason}"


def test_a_failed_search_makes_no_further_calls() -> None:
    fake = _thirty_graded_listings()
    fake.fail("search_active", server_error(), times=3)
    with pytest.raises(MarketResearchError):
        _run(fake)
    assert fake.count("listings_by_ids") == 0


def test_a_failed_review_count_starts_no_new_call() -> None:
    fake = _thirty_graded_listings()
    fake.fail("review_count", server_error(), argument=1)
    with pytest.raises(MarketResearchError):
        _run(fake)
    assert fake.count("review_count") < 20


def test_a_timeout_with_no_message_still_names_a_reason() -> None:
    import httpx

    fake = _thirty_graded_listings()
    fake.fail("listings_by_ids", httpx.ReadTimeout(""))
    with pytest.raises(MarketResearchError) as raised:
        _run(fake)
    assert str(raised.value) == "Etsy market search failed: ReadTimeout"


# ---------------------------------------------------------------- in flight


class _Slow(FakeEtsyMarketClient):
    """Holds each call open briefly and records how many overlapped."""

    def __init__(self) -> None:
        super().__init__()
        self._gauge = threading.Lock()
        self._in_flight = 0
        self.most_in_flight = 0

    def _hold(self) -> None:
        with self._gauge:
            self._in_flight += 1
            self.most_in_flight = max(self.most_in_flight, self._in_flight)
        time.sleep(0.02)
        with self._gauge:
            self._in_flight -= 1

    def search_active(self, query: str, *, limit: int = 25) -> list[MarketCandidate]:
        self._hold()
        return super().search_active(query, limit=limit)

    def review_count(self, listing_id: int) -> int:
        self._hold()
        return super().review_count(listing_id)


def test_no_more_than_five_calls_are_in_flight() -> None:
    fake = _Slow()
    for listing_id in range(1, 31):
        _seed(fake, listing_id)
    fake.seed_search(QUERIES[0], list(range(1, 26)))
    fake.seed_search(QUERIES[1], list(range(6, 31)))

    _run(fake)

    assert fake.count("review_count") == 20
    assert 1 < fake.most_in_flight <= 5
