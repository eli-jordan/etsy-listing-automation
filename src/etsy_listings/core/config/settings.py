"""``settings.yaml``: the workspace's tunable settings, next to ``shop.yaml``.

It holds market scoring weights (features/market-seo-20260924/spec.md,
*Scoring*), the batch AI queue's limit (ADR-0048), the ordered AI provider
preferences (ADR-0056) and the AI time limits (ADR-0057)::

    market_seo:
      weights:
        reviews: 30
...
    batch_ai:
      concurrency: 1
    ai:
      providers: [{name: codex}, {name: claude}, {name: grok}]
      step_limit_minutes: 5
      run_limit_minutes: 20

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
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
)

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


MIN_STEP_LIMIT_MINUTES = 1
MAX_STEP_LIMIT_MINUTES = 15
DEFAULT_STEP_LIMIT_MINUTES = 5
MIN_RUN_LIMIT_MINUTES = 5
MAX_RUN_LIMIT_MINUTES = 60
DEFAULT_RUN_LIMIT_MINUTES = 20
"""ADR-0057's ranges and defaults, in whole minutes. Three providers at the
15-minute maximum need 45, within the 60-minute maximum."""


ProviderName = Literal["codex", "claude", "grok"]
PROVIDER_NAMES: tuple[ProviderName, ...] = ("codex", "claude", "grok")


class AiProviderSettings(BaseModel):
    """One provider's preferences for every task (ADR-0056).

    Discovery is advisory, so model and effort are intentionally not enums.
    A retired value stays usable until the seller replaces it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: ProviderName
    enabled: bool = True
    model: str | None = Field(None, min_length=1)
    effort: str | None = Field(None, min_length=1)


class AiSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    providers: tuple[AiProviderSettings, ...] = Field(
        default_factory=lambda: tuple(AiProviderSettings(name=name) for name in PROVIDER_NAMES)
    )

    step_limit_minutes: int = Field(
        DEFAULT_STEP_LIMIT_MINUTES, ge=MIN_STEP_LIMIT_MINUTES, le=MAX_STEP_LIMIT_MINUTES
    )
    """One provider attempt and its one repair (ADR-0057). Each fallback
    provider gets a fresh allowance, clipped to what is left of the run."""
    run_limit_minutes: int = Field(
        DEFAULT_RUN_LIMIT_MINUTES,
        ge=MIN_RUN_LIMIT_MINUTES,
        le=MAX_RUN_LIMIT_MINUTES,
        # A raised step limit must be checked against the default run limit too.
        validate_default=True,
    )
    """The whole run: every task, its fallbacks and market research. At least
    :meth:`run_floor_minutes`, so each enabled provider has a full step."""

    @field_validator("providers")
    @classmethod
    def valid_chain(
        cls, providers: tuple[AiProviderSettings, ...]
    ) -> tuple[AiProviderSettings, ...]:
        names = [provider.name for provider in providers]
        if len(names) != len(set(names)):
            raise ValueError("duplicate provider names are not allowed")
        if not any(provider.enabled for provider in providers):
            raise ValueError("at least one provider must be enabled")
        return providers

    @field_validator("run_limit_minutes")
    @classmethod
    def covers_every_step(cls, run: int, info: ValidationInfo) -> int:
        """ADR-0057: refused, never raised on load. Fields validate in
        declaration order, so a bad provider list or step limit is already
        reported and missing from ``info.data``; that is not a second error."""
        providers = info.data.get("providers")
        step = info.data.get("step_limit_minutes")
        if providers is None or step is None:
            return run
        floor = run_floor_minutes(providers, step)
        if run < floor:
            enabled = sum(provider.enabled for provider in providers)
            raise ValueError(
                f"must be at least {floor} ({enabled} enabled provider"
                f"{'' if enabled == 1 else 's'} x {step}-minute step limit)"
            )
        return run

    def run_floor_minutes(self) -> int:
        """The lowest run limit this chain and step limit allow."""
        return run_floor_minutes(self.providers, self.step_limit_minutes)


def run_floor_minutes(providers: tuple[AiProviderSettings, ...], step_minutes: int) -> int:
    """``max(5, enabled providers x step)`` (ADR-0057)."""
    enabled = sum(provider.enabled for provider in providers)
    return max(MIN_RUN_LIMIT_MINUTES, enabled * step_minutes)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    market_seo: MarketSeoSettings = Field(default_factory=MarketSeoSettings)
    batch_ai: BatchAiSettings = Field(default_factory=BatchAiSettings)
    ai: AiSettings = Field(default_factory=AiSettings)

    _market_seo_absent = field_validator("market_seo", mode="before")(_absent_is_empty)
    _batch_ai_absent = field_validator("batch_ai", mode="before")(_absent_is_empty)
    _ai_absent = field_validator("ai", mode="before")(_absent_is_empty)

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
