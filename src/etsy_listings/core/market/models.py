from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ScoredListing(BaseModel):
    """One scored comparable listing, as the top listings panel shows it."""

    model_config = ConfigDict(frozen=True, use_attribute_docstrings=True)

    listing_id: int
    rank: int
    """1 is the best score. Ties keep the better search position."""
    score_raw: float
    """Weighted percentile sum ÷ total weight, 0-1: what phrase scores add up."""
    score: int
    """``score_raw`` as a whole number out of 100, as the panel shows it."""
    title: str
    url: str | None
    shop_id: int
    shop_name: str
    own_shop: bool
    """Its ``shop_id`` is ``shop.yaml``'s ``etsy.shop_id``. Our own listings
    are kept: one that ranks is evidence like any other."""
    thumbnail_url: str | None
    search_rank: int
    """Best (lowest) 1-based position across the queries that found it."""
    reviews: int
    favourites_per_day: float | None
    """``None`` when Etsy did not say when the listing was created."""
    views_per_day: float | None
    shop_sales: int
    shop_rating: float | None
    """The shop's ``review_average``; ``None`` for no reviews in a year."""
    tags: tuple[str, ...]
    lead: str
    """The description's first sentence -- all of it the model sees."""


class PhraseScore(BaseModel):
    """One tag the scored listings use, with its normalised score."""

    model_config = ConfigDict(frozen=True)

    phrase: str
    listings: int
    score: float


class MarketResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    queries: tuple[str, ...]
    found: int
    scored: int
    listings: tuple[ScoredListing, ...]
    phrases: tuple[PhraseScore, ...]
    relaxed: bool
    empty: bool
