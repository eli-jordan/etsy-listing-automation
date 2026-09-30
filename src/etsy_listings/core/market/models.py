"""What market research produces (features/market-seo-20260924/spec.md, *Scoring* and *What the
proposal sees*), and the weights it scores with.

All of it is in memory and frozen: research returns a :class:`MarketResult`
and forgets it. Persisting one is the snapshot's job (PR 3), and sending one
to a model is :mod:`etsy_listings.market.block`'s.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from etsy_listings.config.market_weights import METRICS as METRICS
from etsy_listings.config.market_weights import MarketWeights as MarketWeights
from etsy_listings.config.market_weights import Metric as Metric


class ScoredListing(BaseModel):
    """One of the (at most) twenty listings scored, with everything the top
    listings panel shows (features/market-seo-20260924/interactions.md, *Where the data
    comes from*) -- and deliberately not the full description, which neither
    the panel nor the model is given (features/market-seo-20260924/spec.md, *What the proposal
    sees*).
    """

    model_config = ConfigDict(frozen=True)

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
    """One tag used by the scored listings: how many use it, and the sum of
    their scores normalised so the best phrase is 1."""

    model_config = ConfigDict(frozen=True)

    phrase: str
    listings: int
    score: float


class MarketResult(BaseModel):
    """One research run's answer.

    ``found`` counts unique candidates across the three searches; ``scored``
    is how many of them were scored (at most twenty). ``relaxed`` says the
    30-day age filter left nothing and was dropped. ``empty`` says nothing
    was left to score even so -- the one case the proposal goes ahead without
    market data, under a *No comparable listings found* warning.
    """

    model_config = ConfigDict(frozen=True)

    queries: tuple[str, ...]
    found: int
    scored: int
    listings: tuple[ScoredListing, ...]
    phrases: tuple[PhraseScore, ...]
    relaxed: bool
    empty: bool
