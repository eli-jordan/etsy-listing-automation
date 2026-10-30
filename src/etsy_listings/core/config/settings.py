"""``settings.yaml``: the workspace's tunable settings, next to ``shop.yaml``.

It holds two blocks: the market scoring weights (features/market-seo-20260924/spec.md,
*Scoring*) and the batch AI queue's limit (spec, *Batch AI queue*; ADR-0048)::

    market_seo:
      weights:
        reviews: 30
...
    batch_ai:
      concurrency: 1

Everything is optional. A missing file, section or key falls back to the
spec's defaults -- :class:`~etsy_listings.core.market.models.MarketWeights` owns
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

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from etsy_listings.core.config.errors import ConfigLoadError, format_validation_error, parse_yaml
from etsy_listings.core.config.market_weights import MarketWeights

MAX_BATCH_CONCURRENCY = 8
"""Admin plan, *Settings*: Batch AI is a whole-number slider from 1 to 8.
Enforced here, not only by the slider, so a hand edit cannot set a limit
the page could not show."""


def _absent_is_empty(value: Any) -> Any:  # noqa: ANN401 - pre-validation YAML
    """A key written with nothing under it (``market_seo:``) is YAML's
    ``null``; it means "nothing tuned here", the same as leaving it out."""
    return {} if value is None else value


class MarketSeoSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    weights: MarketWeights = Field(default_factory=MarketWeights)

    _weights_absent = field_validator("weights", mode="before")(_absent_is_empty)


class BatchAiSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    concurrency: int = Field(1, ge=1, le=MAX_BATCH_CONCURRENCY)
    """How many batch rows draft at once, across every batch. Manual
    editor runs do not count against it. One by default: a seller's
    provider CLI is usually on a plan with a rate limit, and a queue that
    ran every row at once would spend it on the first batch. At most
    :data:`MAX_BATCH_CONCURRENCY`, the Admin page slider's top."""


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    market_seo: MarketSeoSettings = Field(default_factory=MarketSeoSettings)
    batch_ai: BatchAiSettings = Field(default_factory=BatchAiSettings)

    _market_seo_absent = field_validator("market_seo", mode="before")(_absent_is_empty)
    _batch_ai_absent = field_validator("batch_ai", mode="before")(_absent_is_empty)

    @classmethod
    def load(cls, path: Path) -> Settings:
        """The file at ``path``, or every default when there is none. Errors
        are :class:`ConfigLoadError`, naming the file and the dotted key."""
        if not path.is_file():
            return cls()
        return cls.from_text(path, path.read_text(encoding="utf-8"))

    @classmethod
    def from_text(cls, path: Path, text: str) -> Settings:
        """``text``, read from ``path``, under :meth:`load`'s rules."""
        return cls.from_document(path, parse_yaml(path, text))

    @classmethod
    def from_document(cls, path: Path, raw: object) -> Settings:
        """A parsed document under :meth:`load`'s rules: an empty one is every
        default; anything else must be a mapping of known keys."""
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
