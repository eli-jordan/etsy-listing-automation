"""``settings.yaml``: the workspace's tunable settings, next to ``shop.yaml``.

Today it holds one block, the market scoring weights (market-seo.md,
*Scoring*)::

    market_seo:
      weights:
        reviews: 30
        ...

Everything is optional. A missing file, section or key falls back to the
spec's defaults -- :class:`~etsy_listings.market.models.MarketWeights` owns
those, and its validation (no negatives, not all zero, no unknown metric) is
the file's. Unknown keys are refused rather than ignored: a misspelt
``market-seo:`` that quietly changed nothing would look like tuning that
did not work.

Kept apart from ``shop.yaml`` because that file describes the shop and is
largely written by ``setup``; these are the seller's own knobs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from etsy_listings.config.errors import ConfigLoadError, format_validation_error
from etsy_listings.market.models import MarketWeights


def _absent_is_empty(value: Any) -> Any:  # noqa: ANN401 - pre-validation YAML
    """A key written with nothing under it (``market_seo:``) is YAML's
    ``null``; it means "nothing tuned here", the same as leaving it out."""
    return {} if value is None else value


class MarketSeoSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    weights: MarketWeights = Field(default_factory=MarketWeights)

    _weights_absent = field_validator("weights", mode="before")(_absent_is_empty)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    market_seo: MarketSeoSettings = Field(default_factory=MarketSeoSettings)

    _market_seo_absent = field_validator("market_seo", mode="before")(_absent_is_empty)

    @classmethod
    def load(cls, path: Path) -> Settings:
        """The file at ``path``, or every default when there is none. Errors
        are :class:`ConfigLoadError`, naming the file and the dotted key."""
        if not path.is_file():
            return cls()
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ConfigLoadError(path, f"not valid YAML: {exc}") from exc
        if raw is None:
            return cls()
        if not isinstance(raw, dict):
            raise ConfigLoadError(
                path, f"expected a mapping of settings, found {type(raw).__name__}"
            )
        try:
            return cls.model_validate(raw)
        except ValidationError as exc:
            raise format_validation_error(path, exc) from exc
