"""Workspace-owned market scoring weights."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Metric = Literal[
    "reviews",
    "favourites_per_day",
    "search_rank",
    "views_per_day",
    "shop_sales",
    "shop_rating",
]
"""The six scoring metrics, spelled as ``settings.yaml``'s weight keys."""

METRICS: tuple[Metric, ...] = (
    "reviews",
    "favourites_per_day",
    "search_rank",
    "views_per_day",
    "shop_sales",
    "shop_rating",
)


class MarketWeights(BaseModel):
    """How much each metric counts, relative to the others -- the spec's
    starting values, expected to be tuned through ``settings.yaml`` (PR 3).

    Relative, so they need not sum to 100; but not all zero, since a score
    divided by a total weight of nothing is not a score.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    reviews: float = Field(default=30, ge=0)
    favourites_per_day: float = Field(default=30, ge=0)
    search_rank: float = Field(default=20, ge=0)
    views_per_day: float = Field(default=10, ge=0)
    shop_sales: float = Field(default=5, ge=0)
    shop_rating: float = Field(default=5, ge=0)

    @model_validator(mode="after")
    def _some_weight(self) -> Self:
        if not any(getattr(self, metric) for metric in METRICS):
            raise ValueError("at least one market_seo weight must be above zero")
        return self

    def of(self, metric: Metric) -> float:
        value: float = getattr(self, metric)
        return value
