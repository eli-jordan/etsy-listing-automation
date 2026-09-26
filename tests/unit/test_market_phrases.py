"""The ranked phrase list (market-seo.md, *What the proposal sees*, part 1).

Each tag the scored listings use, with how many listings use it and a phrase
score: the sum of those listings' scores, normalised so the best phrase is 1.
Code does this counting because models are unreliable at it.
"""

from __future__ import annotations

import pytest

from etsy_listings.market.models import ScoredListing
from etsy_listings.market.phrases import rank_phrases


def _scored(listing_id: int, score_raw: float, *tags: str) -> ScoredListing:
    return ScoredListing(
        listing_id=listing_id,
        rank=listing_id,
        score_raw=score_raw,
        score=round(score_raw * 100),
        title=f"Listing {listing_id}",
        url=None,
        shop_id=1,
        shop_name="Shop",
        own_shop=False,
        thumbnail_url=None,
        search_rank=listing_id,
        reviews=0,
        favourites_per_day=0.0,
        views_per_day=0.0,
        shop_sales=0,
        shop_rating=None,
        tags=tags,
        lead="",
    )


def _table(listings: list[ScoredListing], limit: int = 40) -> list[tuple[str, int, float]]:
    return [(p.phrase, p.listings, p.score) for p in rank_phrases(listings, limit=limit)]


def test_a_phrase_scores_the_sum_of_its_listings_normalised_to_the_best() -> None:
    listings = [
        _scored(1, 0.8, "hiking shirt", "retro sunset"),
        _scored(2, 0.6, "hiking shirt", "camping tee"),
        _scored(3, 0.2, "retro sunset"),
    ]
    # hiking shirt 0.8 + 0.6 = 1.4 (best, so 1); retro sunset 0.8 + 0.2 = 1.0;
    # camping tee 0.6.
    assert _table(listings) == pytest.approx(
        [("hiking shirt", 2, 1.0), ("retro sunset", 2, 1.0 / 1.4), ("camping tee", 1, 0.6 / 1.4)]
    )


def test_a_phrase_used_by_more_weaker_listings_can_rank_below_fewer_stronger_ones() -> None:
    """The mockup's *hiker gift* (14 listings, 0.94) under *retro hiking
    shirt* (12, 1): the score, not the count, orders the list."""
    listings = [
        _scored(1, 0.9, "strong"),
        _scored(2, 0.1, "weak"),
        _scored(3, 0.1, "weak"),
        _scored(4, 0.1, "weak"),
    ]
    assert [row[:2] for row in _table(listings)] == [("strong", 1), ("weak", 3)]


def test_tags_differing_only_in_case_or_spacing_are_one_phrase() -> None:
    listings = [
        _scored(1, 0.5, "Hiking  Shirt"),
        _scored(2, 0.5, " hiking shirt "),
    ]
    assert _table(listings) == [("hiking shirt", 2, 1.0)]


def test_a_listing_repeating_a_tag_counts_once() -> None:
    listings = [_scored(1, 0.5, "tee", "Tee"), _scored(2, 0.4, "shirt")]
    assert _table(listings) == pytest.approx([("tee", 1, 1.0), ("shirt", 1, 0.8)])


def test_ties_order_by_listing_count_then_alphabetically() -> None:
    listings = [
        _scored(1, 0.5, "zebra", "apple"),
        _scored(2, 0.25, "mango"),
        _scored(3, 0.25, "mango"),
        _scored(4, 0.0, "blank"),
    ]
    # apple, zebra and mango all sum to 0.5; mango has two listings.
    assert [row[0] for row in _table(listings)] == ["mango", "apple", "zebra", "blank"]


def test_only_the_top_forty_are_listed() -> None:
    listings = [_scored(1, 1.0, *(f"phrase {n:02d}" for n in range(13)))] + [
        _scored(n, 1.0 - n / 100, *(f"tag {n} {k}" for k in range(13))) for n in range(2, 5)
    ]
    ranked = _table(listings)
    assert len(ranked) == 40
    assert ranked[0][0] == "phrase 00"


def test_blank_tags_and_scoreless_sets_are_handled() -> None:
    assert _table([]) == []
    assert _table([_scored(1, 0.0, "tee", "  ")]) == [("tee", 1, 0.0)]
