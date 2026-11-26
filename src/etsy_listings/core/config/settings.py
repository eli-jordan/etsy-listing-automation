from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    ValidatorFunctionWrapHandler,
    field_validator,
)

from etsy_listings.core.config.errors import ConfigLoadError, format_validation_error, parse_yaml
from etsy_listings.core.config.market_weights import MarketWeights

MAX_BATCH_CONCURRENCY = 8
"""Admin plan, *Settings*: Batch AI is a whole-number slider from 1 to 8.
Enforced here, not only by the slider, so a hand edit cannot set a limit
the page could not show."""


def _absent_is_empty(value: object) -> object:
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
    """One provider's preferences for every task."""

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
        # pydantic runs no validator on a default unless asked.
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
        # pydantic leaves a field that failed validation out of info.data.
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
        return run_floor_minutes(self.providers, self.step_limit_minutes)


def run_floor_minutes(providers: tuple[AiProviderSettings, ...], step_minutes: int) -> int:
    enabled = sum(provider.enabled for provider in providers)
    return max(MIN_RUN_LIMIT_MINUTES, enabled * step_minutes)


class PositionScaleLimits(BaseModel):
    """Interactions' slider ranges guarantee min <= identity <= max (ADR-0058)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    min: float = Field(0.80, ge=0.50, le=1.0, allow_inf_nan=False)
    max: float = Field(1.10, ge=1.0, le=1.50, allow_inf_nan=False)


class TemplatePositionLimits(BaseModel):
    """Mockup-only similarity limits; offsets are fractions of the box's rectified W and H."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scale: PositionScaleLimits = Field(default_factory=PositionScaleLimits)
    offset: float = Field(0.10, ge=0, le=0.25, allow_inf_nan=False)
    rotation: float = Field(15, ge=0, le=30, allow_inf_nan=False)


def _native(value: str) -> Path:
    """``userpath.to_native_path``, imported here because ``core.workspace``'s
    initialiser imports this module."""
    from etsy_listings.core.workspace.userpath import to_native_path  # noqa: PLC0415 -- cycle

    return to_native_path(value)


BACKUP_INTERVAL_HOURS = (4, 6, 12, 24, 48)
"""The intervals the Backup page offers (workspace-backup spec, *Scheduling*).
Enforced here so a hand edit cannot set one the page could not show."""

BackupIntervalHours = Literal[4, 6, 12, 24, 48]


class RetentionSettings(BaseModel):
    """What ``restic forget`` keeps: every snapshot from the last
    ``keep_within_days``, then the latest of each of the last ``weekly`` weeks
    and ``monthly`` months (spec, *Backup run* step 5). At least one of each,
    because zero would let a forget remove the snapshot it just made."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    keep_within_days: int = Field(7, ge=1)
    weekly: int = Field(4, ge=1)
    monthly: int = Field(3, ge=1)


class BackupSettings(BaseModel):
    """The ``backup:`` block. Paths are this machine's, and the block travels
    with the workspace, so a path that no longer exists is not refused here:
    the backup reports a missing repository instead, and the rest of the app
    keeps loading its settings."""

    model_config = ConfigDict(extra="forbid", frozen=True, use_attribute_docstrings=True)

    repository: Path
    """The backup storage folder: the local restic repository."""
    destinations: tuple[Path, ...] = ()
    """Folders the repository is copied to one way, in order."""
    interval_hours: BackupIntervalHours = 12
    retention: RetentionSettings = Field(default_factory=RetentionSettings)
    restic_binary: Path | None = None
    """Another restic to run instead of the pinned download."""
    workspace_id: str | None = None
    """A random UUID set-up writes once. Every snapshot is tagged with it and
    retention groups this workspace's snapshots by it, so a renamed PC or a
    moved workspace keeps one schedule. Not shown in Setup."""

    _retention_absent = field_validator("retention", mode="before")(_absent_is_empty)

    @field_validator("repository", "restic_binary", mode="before")
    @classmethod
    def native_path(cls, value: object) -> object:
        # Before pydantic makes a Path: on Windows that reads /cygdrive/c as \cygdrive\c.
        return _native(value) if isinstance(value, str) else value

    @field_validator("workspace_id")
    @classmethod
    def a_uuid(cls, value: str | None) -> str | None:
        # The canonical form, so it is a valid restic tag.
        if value is None:
            return None
        try:
            return str(uuid.UUID(value))
        except ValueError:
            raise ValueError(
                "must be the workspace ID set-up wrote, a UUID; delete the line to get a new one"
            ) from None

    @field_validator("destinations", mode="before")
    @classmethod
    def native_paths(cls, value: object) -> object:
        if isinstance(value, list | tuple):
            return [_native(item) if isinstance(item, str) else item for item in value]
        return value

    @field_validator("interval_hours", mode="wrap")
    @classmethod
    def offered_interval(cls, value: object, handler: ValidatorFunctionWrapHandler) -> int:
        try:
            return int(handler(value))
        except ValidationError:
            choices = ", ".join(str(hours) for hours in BACKUP_INTERVAL_HOURS[:-1])
            raise ValueError(f"must be {choices} or {BACKUP_INTERVAL_HOURS[-1]}") from None


@dataclass(frozen=True)
class SettingsProblem:
    message: str


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    market_seo: MarketSeoSettings = Field(default_factory=MarketSeoSettings)
    batch_ai: BatchAiSettings = Field(default_factory=BatchAiSettings)
    ai: AiSettings = Field(default_factory=AiSettings)
    template_positions: TemplatePositionLimits = Field(default_factory=TemplatePositionLimits)
    backup: BackupSettings | None = None
    """Off when absent, and also when written empty (``backup:``): unlike the
    sections above it gets no ``_absent_is_empty``, because there is no
    default repository to turn an empty block into."""

    _market_seo_absent = field_validator("market_seo", mode="before")(_absent_is_empty)
    _batch_ai_absent = field_validator("batch_ai", mode="before")(_absent_is_empty)
    _ai_absent = field_validator("ai", mode="before")(_absent_is_empty)
    _positions_absent = field_validator("template_positions", mode="before")(_absent_is_empty)

    @classmethod
    def load(cls, path: Path) -> Settings:
        if not path.is_file():
            return cls()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ConfigLoadError(path, f"cannot be read: {exc}") from exc
        return cls.from_text(path, text)

    @classmethod
    def from_text(cls, path: Path, text: str) -> Settings:
        return cls.from_document(path, parse_yaml(path, text))

    @classmethod
    def from_document(cls, path: Path, raw: object) -> Settings:
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
