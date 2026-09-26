"""Scoring maths for market research (market-seo.md, *Scoring*).

Every metric becomes a 0-1 percentile within the set being scored, so one
viral listing cannot swamp the rest and metrics on different scales add up.
Expected values are worked by hand from the spec's rules, not recomputed the
way the code computes them.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from etsy_listings.market.models import MarketWeights
from etsy_listings.market.scoring import display_score, percentiles, rescaled


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        # Distinct values spread evenly from 0 (worst) to 1 (best).
        ([10.0, 30.0, 20.0], [0.0, 1.0, 0.5]),
        ([5.0, 1.0, 3.0, 2.0, 4.0], [1.0, 0.0, 0.5, 0.25, 0.75]),
        # Ties share the average of the positions they occupy: the two 7s
        # sit at positions 1 and 2 of 0..3, so each gets 1.5 / 3.
        ([1.0, 7.0, 7.0, 9.0], [0.0, 0.5, 0.5, 1.0]),
        # Everything tied is everything in the middle.
        ([4.0, 4.0, 4.0], [0.5, 0.5, 0.5]),
        # A single listing is trivially tied with itself.
        ([42.0], [0.5]),
        ([], []),
        # A missing value (a shop with no rating, an unknown age) ranks below
        # every real one, zero included -- and missing values tie together.
        ([None, 0.0, 4.5], [0.0, 0.5, 1.0]),
        ([None, None, 3.0, 1.0], [1 / 6, 1 / 6, 1.0, 2 / 3]),
    ],
)
def test_percentiles(values: list[float | None], expected: list[float]) -> None:
    assert percentiles(values) == pytest.approx(expected)


def test_default_weights_are_the_spec_table() -> None:
    weights = MarketWeights()
    assert weights.model_dump() == {
        "reviews": 30,
        "favourites_per_day": 30,
        "search_rank": 20,
        "views_per_day": 10,
        "shop_sales": 5,
        "shop_rating": 5,
    }


def test_preliminary_weights_leave_reviews_out_and_sum_to_one() -> None:
    # 30 + 20 + 10 + 5 + 5 = 70 without reviews.
    assert rescaled(MarketWeights(), exclude={"reviews"}) == pytest.approx(
        {
            "favourites_per_day": 30 / 70,
            "search_rank": 20 / 70,
            "views_per_day": 10 / 70,
            "shop_sales": 5 / 70,
            "shop_rating": 5 / 70,
        }
    )


def test_final_weights_are_relative_so_any_total_works() -> None:
    weights = MarketWeights(
        reviews=1,
        favourites_per_day=1,
        search_rank=2,
        views_per_day=0,
        shop_sales=0,
        shop_rating=0,
    )
    assert rescaled(weights) == pytest.approx(
        {
            "reviews": 0.25,
            "favourites_per_day": 0.25,
            "search_rank": 0.5,
            "views_per_day": 0.0,
            "shop_sales": 0.0,
            "shop_rating": 0.0,
        }
    )


def test_rescaling_nothing_but_reviews_gives_all_zero_weights() -> None:
    """Only reviews weighted: the preliminary ranking has no signal at all,
    so every weight is zero and search rank's tie-break decides the order."""
    weights = MarketWeights(
        reviews=1,
        favourites_per_day=0,
        search_rank=0,
        views_per_day=0,
        shop_sales=0,
        shop_rating=0,
    )
    assert set(rescaled(weights, exclude={"reviews"}).values()) == {0.0}


def test_weights_refuse_negatives_and_an_all_zero_set() -> None:
    with pytest.raises(ValidationError):
        MarketWeights(reviews=-1)
    with pytest.raises(ValidationError):
        MarketWeights(
            reviews=0,
            favourites_per_day=0,
            search_rank=0,
            views_per_day=0,
            shop_sales=0,
            shop_rating=0,
        )


@pytest.mark.parametrize(
    ("raw", "shown"),
    [(0.0, 0), (1.0, 100), (0.873, 87), (0.875, 88), (0.125, 13), (0.5, 50)],
)
def test_display_score_rounds_half_up_to_a_whole_number(raw: float, shown: int) -> None:
    assert display_score(raw) == shown
