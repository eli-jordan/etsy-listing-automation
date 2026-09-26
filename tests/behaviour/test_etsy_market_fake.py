"""The in-memory Etsy market that research's behaviour tests will run against.

It has to be faithful in the ways research can observe: results in the order a
search ranked them, the batch counted per chunk of a hundred as the real one
is, ids it does not know absent from the batch rather than invented, and every
call -- failed ones included, since they cost quota too -- in the call log that
PR 2's "at most 3 + 1 + 20 calls" assertion reads.
"""

from __future__ import annotations

import threading

import httpx
import pytest

from etsy_listings.clients.etsy.fakes import (
    FakeEtsyMarketClient,
    MarketCall,
    market_listing,
    network_error,
    rate_limited,
    server_error,
)
from etsy_listings.clients.etsy.market import EtsyMarketClient
from etsy_listings.clients.etsy.models import MarketCandidate, ShopStats
from etsy_listings.clients.etsy.transport import EtsyApiError


def _seeded() -> FakeEtsyMarketClient:
    fake = FakeEtsyMarketClient()
    fake.seed_listing(
        market_listing(
            1,
            title="Retro Sunset Hiking Shirt",
            tags=("hiking shirt", "retro sunset"),
            shop=ShopStats(shop_name="TrailTees", review_average=4.8, review_count=90),
            thumbnail_url="https://img.test/1_170x135.jpg",
        ),
        reviews=12,
    )
    fake.seed_listing(market_listing(2, title="Mountain Tee"), reviews=0)
    fake.seed_listing(market_listing(3, title="Camping Shirt"))
    fake.seed_search("retro sunset hiking shirt", [2, 1])
    fake.seed_search("camping shirt", [3, 1])
    return fake


def test_the_fake_satisfies_the_protocol() -> None:
    client: EtsyMarketClient = FakeEtsyMarketClient()

    assert client.search_active("anything") == []


def test_a_search_answers_the_seeded_listings_in_rank_order_as_candidates() -> None:
    found = _seeded().search_active("retro sunset hiking shirt")

    assert [c.listing_id for c in found] == [2, 1]
    assert all(type(c) is MarketCandidate for c in found)
    assert found[1].title == "Retro Sunset Hiking Shirt"


def test_a_search_honours_its_limit() -> None:
    assert [c.listing_id for c in _seeded().search_active("camping shirt", limit=1)] == [3]


def test_an_unseeded_query_finds_nothing() -> None:
    assert _seeded().search_active("velvet ballgown") == []


def test_the_batch_answers_known_ids_with_their_stats_and_leaves_unknown_ones_out() -> None:
    [one] = _seeded().listings_by_ids([1, 99])

    assert one.listing_id == 1
    assert one.shop == ShopStats(shop_name="TrailTees", review_average=4.8, review_count=90)
    assert one.thumbnail_url == "https://img.test/1_170x135.jpg"


def test_review_counts_are_the_seeded_ones_and_zero_otherwise() -> None:
    fake = _seeded()

    assert fake.review_count(1) == 12
    assert fake.review_count(3) == 0


def test_every_call_is_logged_with_what_it_asked_and_the_batch_once_per_chunk() -> None:
    fake = _seeded()

    fake.search_active("camping shirt")
    fake.listings_by_ids(list(range(1, 151)))
    fake.review_count(1)

    assert fake.calls == [
        MarketCall("search_active", "camping shirt"),
        MarketCall("listings_by_ids", tuple(range(1, 101))),
        MarketCall("listings_by_ids", tuple(range(101, 151))),
        MarketCall("review_count", 1),
    ]
    assert fake.count("listings_by_ids") == 2


def test_an_empty_batch_is_not_a_call() -> None:
    fake = _seeded()

    assert fake.listings_by_ids([]) == []
    assert fake.calls == []


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (rate_limited(), EtsyApiError),
        (server_error(), EtsyApiError),
        (network_error(), httpx.TransportError),
    ],
)
def test_an_injected_failure_raises_what_the_real_client_would_once_retries_run_out(
    error: Exception, expected: type[Exception]
) -> None:
    fake = _seeded()
    fake.fail("search_active", error)

    with pytest.raises(expected):
        fake.search_active("camping shirt")

    assert fake.calls == [MarketCall("search_active", "camping shirt")]
    assert [c.listing_id for c in fake.search_active("camping shirt")] == [3, 1]


def test_the_injected_statuses_are_the_ones_named() -> None:
    assert rate_limited().status_code == 429
    assert server_error().status_code == 503
    assert server_error(502).status_code == 502


def test_a_failure_can_be_injected_for_several_calls_and_for_one_argument() -> None:
    fake = _seeded()
    fake.fail("review_count", server_error(), times=2, argument=3)

    assert fake.review_count(1) == 12
    for _ in range(2):
        with pytest.raises(EtsyApiError):
            fake.review_count(3)
    assert fake.review_count(3) == 0


def test_the_fake_is_safe_to_call_from_five_threads() -> None:
    fake = _seeded()
    fake.fail("review_count", server_error(), times=3)
    failures: list[Exception] = []
    lock = threading.Lock()

    def call() -> None:
        for _ in range(20):
            try:
                fake.review_count(1)
            except EtsyApiError as exc:
                with lock:
                    failures.append(exc)

    threads = [threading.Thread(target=call) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert fake.count("review_count") == 100
    assert len(failures) == 3


def test_a_seeded_listing_is_its_own_copy() -> None:
    """Seeding the same id again replaces it -- research's tests re-seed a
    listing to change one signal between two runs."""
    fake = _seeded()
    fake.seed_listing(market_listing(1, num_favorers=500), reviews=1)

    [one] = fake.listings_by_ids([1])
    assert one.num_favorers == 500
    assert fake.review_count(1) == 1
