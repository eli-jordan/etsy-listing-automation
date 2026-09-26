"""The 7-day market caches (market-seo.md, *Cache*; implementation plan, PR 3).

Behaviour through the client's own three calls, against the in-memory Etsy
market with an injected clock: what reaches Etsy is read from the fake's call
log, since a call that reaches Etsy is quota spent.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from etsy_listings.clients.etsy import market
from etsy_listings.clients.etsy.fakes import FakeEtsyMarketClient, market_listing
from etsy_listings.market import research
from etsy_listings.market.cache import CachedEtsyMarketClient
from etsy_listings.workspace.workspace import Workspace

DAY = 86_400.0
WEEK = 7 * DAY
TODAY = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
QUERIES = ("retro sunset hiking shirt", "mountain sunset tee", "hiking gift shirt")


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


def _market() -> FakeEtsyMarketClient:
    fake = FakeEtsyMarketClient()
    for listing_id in (1, 2, 3):
        fake.seed_listing(market_listing(listing_id), reviews=listing_id * 10)
    fake.seed_search("hiking shirt", [1, 2, 3])
    return fake


def _cached(fake: FakeEtsyMarketClient, tmp_path: Path, clock: Clock) -> CachedEtsyMarketClient:
    return CachedEtsyMarketClient(
        fake, search_dir=tmp_path / "search", stats_dir=tmp_path / "stats", clock=clock
    )


def test_a_repeated_search_is_answered_from_the_cache(tmp_path: Path) -> None:
    fake, clock = _market(), Clock()
    cached = _cached(fake, tmp_path, clock)

    first = cached.search_active("hiking shirt", limit=25)
    second = cached.search_active("hiking shirt", limit=25)

    assert [c.listing_id for c in first] == [1, 2, 3]
    assert second == first
    assert fake.count("search_active") == 1


def test_a_search_is_asked_again_once_seven_days_have_passed(tmp_path: Path) -> None:
    fake, clock = _market(), Clock()
    cached = _cached(fake, tmp_path, clock)

    cached.search_active("hiking shirt")
    clock.now += WEEK - 1
    cached.search_active("hiking shirt")
    assert fake.count("search_active") == 1

    clock.now += 1
    cached.search_active("hiking shirt")
    cached.search_active("hiking shirt")
    assert fake.count("search_active") == 2


def test_the_search_key_includes_every_search_parameter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The query, the page size, and the parameters every search sends
    (sort order, buyer country): change any one and it is a new question."""
    fake, clock = _market(), Clock()
    fake.seed_search("hiking tee", [3])
    cached = _cached(fake, tmp_path, clock)

    cached.search_active("hiking shirt", limit=25)
    cached.search_active("hiking tee", limit=25)
    cached.search_active("hiking shirt", limit=10)
    assert fake.count("search_active") == 3

    monkeypatch.setitem(market.SEARCH_DEFAULTS, "buyer_country", "GB")
    cached.search_active("hiking shirt", limit=25)
    monkeypatch.setitem(market.SEARCH_DEFAULTS, "sort_on", "created")
    cached.search_active("hiking shirt", limit=25)
    assert fake.count("search_active") == 5


def test_text_comes_back_from_the_cache_exactly_as_decoded(tmp_path: Path) -> None:
    """Etsy's text is unescaped once, on the way in. A seller who typed a
    literal ``&amp;`` keeps it on a cache hit."""
    fake, clock = FakeEtsyMarketClient(), Clock()
    # As Etsy sends it: the seller typed a literal "&amp;", and Etsy escaped that.
    fake.seed_listing(market_listing(9, title="Salt &amp;amp; Pepper", tags=["r&amp;amp;b tee"]))
    fake.seed_search("tee", [9])
    cached = _cached(fake, tmp_path, clock)

    fresh = cached.search_active("tee")
    again = cached.search_active("tee")

    assert again == fresh
    assert again[0].title == "Salt &amp; Pepper"
    assert again[0].tags == ("r&amp;b tee",)


def test_an_unreadable_cache_file_is_a_miss_not_an_error(tmp_path: Path) -> None:
    fake, clock = _market(), Clock()
    cached = _cached(fake, tmp_path, clock)
    cached.search_active("hiking shirt")
    for entry in (tmp_path / "search").iterdir():
        entry.write_text("{not json", encoding="utf-8")

    assert [c.listing_id for c in cached.search_active("hiking shirt")] == [1, 2, 3]
    assert fake.count("search_active") == 2
    assert [c.listing_id for c in cached.search_active("hiking shirt")] == [1, 2, 3]
    assert fake.count("search_active") == 2


# ------------------------------------------------------------------ stats


def test_listing_stats_are_cached_per_listing(tmp_path: Path) -> None:
    """Keyed by ``listing_id``, not by the batch: a later batch that shares
    listings with an earlier one only asks Etsy about the new ones."""
    fake, clock = _market(), Clock()
    fake.seed_listing(market_listing(4))
    cached = _cached(fake, tmp_path, clock)

    first = cached.listings_by_ids([1, 2])
    again = cached.listings_by_ids([2, 1])
    wider = cached.listings_by_ids([1, 2, 3, 4])

    assert [listing.listing_id for listing in first] == [1, 2]
    assert [listing.listing_id for listing in again] == [2, 1]
    assert [listing.listing_id for listing in wider] == [1, 2, 3, 4]
    assert wider[0] == first[0]
    assert [call.argument for call in fake.calls] == [(1, 2), (3, 4)]


def test_a_listing_etsy_no_longer_has_is_remembered_as_gone(tmp_path: Path) -> None:
    fake, clock = _market(), Clock()
    cached = _cached(fake, tmp_path, clock)

    assert [listing.listing_id for listing in cached.listings_by_ids([1, 99])] == [1]
    assert [listing.listing_id for listing in cached.listings_by_ids([99, 1])] == [1]
    assert fake.count("listings_by_ids") == 1


def test_listing_stats_are_asked_again_after_seven_days(tmp_path: Path) -> None:
    fake, clock = _market(), Clock()
    cached = _cached(fake, tmp_path, clock)

    cached.listings_by_ids([1])
    clock.now += WEEK - 1
    cached.listings_by_ids([1])
    assert fake.count("listings_by_ids") == 1

    clock.now += 1
    cached.listings_by_ids([1])
    assert fake.count("listings_by_ids") == 2


def test_review_counts_are_cached_per_listing_for_seven_days(tmp_path: Path) -> None:
    fake, clock = _market(), Clock()
    cached = _cached(fake, tmp_path, clock)

    assert cached.review_count(2) == 20
    assert cached.review_count(2) == 20
    assert cached.review_count(3) == 30
    assert fake.count("review_count") == 2

    clock.now += WEEK
    assert cached.review_count(2) == 20
    assert fake.count("review_count") == 3


def test_a_review_count_and_the_batch_fields_age_separately(tmp_path: Path) -> None:
    """Both live in one listing's entry, but were fetched at different
    moments -- each expires on its own clock."""
    fake, clock = _market(), Clock()
    cached = _cached(fake, tmp_path, clock)

    cached.listings_by_ids([1])
    clock.now += 3 * DAY
    cached.review_count(1)
    clock.now += 5 * DAY  # the batch fields are 8 days old, the count 5

    cached.listings_by_ids([1])
    cached.review_count(1)

    assert fake.count("listings_by_ids") == 2
    assert fake.count("review_count") == 1


def test_a_stats_entry_of_the_wrong_shape_is_a_miss(tmp_path: Path) -> None:
    fake, clock = _market(), Clock()
    cached = _cached(fake, tmp_path, clock)
    cached.listings_by_ids([1])
    cached.review_count(1)
    entry = tmp_path / "stats" / "1.json"
    entry.write_text(
        json.dumps(
            {
                "schema": 1,
                "listing": {"fetched_at": clock.now, "data": {"title": "no ids"}},
                "reviews": {"fetched_at": clock.now, "data": "ten"},
            }
        ),
        encoding="utf-8",
    )

    assert [listing.listing_id for listing in cached.listings_by_ids([1])] == [1]
    assert cached.review_count(1) == 10
    assert fake.count("listings_by_ids") == 2
    assert fake.count("review_count") == 2


# --------------------------------------------------------------- research


def _research_market() -> FakeEtsyMarketClient:
    """Enough listings that research rations review counts (25 per query,
    overlapping), all old enough to score."""
    fake = FakeEtsyMarketClient()
    created = int(TODAY.timestamp()) - 100 * int(DAY)
    for listing_id in range(1, 41):
        fake.seed_listing(
            market_listing(
                listing_id,
                num_favorers=listing_id,
                views=10 * listing_id,
                original_creation_timestamp=created,
                tags=[f"tag {listing_id % 7}"],
            ),
            reviews=listing_id % 5,
        )
    fake.seed_search(QUERIES[0], range(1, 26))
    fake.seed_search(QUERIES[1], range(10, 35))
    fake.seed_search(QUERIES[2], range(16, 41))
    return fake


def test_a_second_research_with_the_same_queries_makes_no_etsy_calls(tmp_path: Path) -> None:
    fake, clock = _research_market(), Clock()

    first = research(QUERIES, _cached(fake, tmp_path, clock), today=TODAY)
    calls_first = len(fake.calls)
    clock.now += WEEK - 60
    second = research(QUERIES, _cached(fake, tmp_path, clock), today=TODAY)

    assert calls_first == 3 + 1 + 20
    assert len(fake.calls) == calls_first
    assert second == first


def test_research_asks_etsy_again_once_the_week_is_up(tmp_path: Path) -> None:
    fake, clock = _research_market(), Clock()

    research(QUERIES, _cached(fake, tmp_path, clock), today=TODAY)
    clock.now += WEEK
    research(QUERIES, _cached(fake, tmp_path, clock), today=TODAY)

    assert len(fake.calls) == 2 * (3 + 1 + 20)


def test_in_a_workspace_the_caches_live_under_cache_market(workspace_root: Path) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    fake = _market()
    cached = CachedEtsyMarketClient.in_workspace(fake, workspace)

    cached.search_active("hiking shirt")
    cached.review_count(1)

    assert len(list(workspace.market_search_cache_dir().glob("*.json"))) == 1
    assert (workspace.market_stats_cache_dir() / "1.json").is_file()


def _rewrite_search_entry(tmp_path: Path, **changes: object) -> None:
    (entry,) = (tmp_path / "search").iterdir()
    payload = json.loads(entry.read_text(encoding="utf-8"))
    entry.write_text(json.dumps(payload | changes), encoding="utf-8")


def test_a_search_entry_of_the_wrong_shape_is_a_miss(tmp_path: Path) -> None:
    fake, clock = _market(), Clock()
    cached = _cached(fake, tmp_path, clock)
    cached.search_active("hiking shirt")
    _rewrite_search_entry(tmp_path, data=[{"title": "no ids"}])

    assert [c.listing_id for c in cached.search_active("hiking shirt")] == [1, 2, 3]
    assert fake.count("search_active") == 2


def test_an_entry_an_older_build_wrote_is_a_miss(tmp_path: Path) -> None:
    fake, clock = _market(), Clock()
    cached = _cached(fake, tmp_path, clock)
    cached.search_active("hiking shirt")
    _rewrite_search_entry(tmp_path, schema=0)

    cached.search_active("hiking shirt")
    assert fake.count("search_active") == 2
