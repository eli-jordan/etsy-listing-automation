from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from etsy_listings.core.config.settings import (
    DEFAULT_RUN_LIMIT_MINUTES,
    DEFAULT_STEP_LIMIT_MINUTES,
    AiSettings,
)

RationaleIntent = Literal["core_product", "bottom_of_funnel", "style"]
RationaleField = Literal["title", "tags", "description_lead"]
WarningKind = Literal["general", "trademark"]


@dataclass(frozen=True)
class ProviderTask:
    """One complete unit of work for a provider CLI, with nothing in it that
    says which AI feature asked.

    This is the seam that lets brief drafting and SEO generation share one
    Codex adapter, one Claude adapter, one fallback order, one repair rule
    and one deadline. An adapter's job was always "run the CLI read-only
    against this prompt, hand it this schema, let it see this image, return
    what it printed" -- what made that look SEO-shaped was only that the
    adapter itself assembled the prompt from `prompts/seo.md`. Assembling it
    is the caller's now (`ai/prompt.py.build_seo_task`,
    `ai/brief.py.build_brief_task`), which also settles a question two
    readiness checks used to answer differently: a missing prompt file makes
    a *request* impossible, not a CLI unready, so it is no longer part of
    `readiness()`.

    ``prompt_text`` is already complete -- seller prose, delimited context,
    schema and all. A repair call appends to it (`ai/repair.py`); nothing
    else ever rewrites it.
    """

    prompt_text: str
    response_schema: Mapping[str, Any]
    design_image: Path


@dataclass(frozen=True)
class GarmentContext:
    brand: str
    model: str


@dataclass(frozen=True)
class SeoRequest:
    brief: str
    product_type: str
    etsy_category: str
    materials: tuple[str, ...]
    colors: tuple[str, ...]
    garment: GarmentContext
    design_image: Path
    market_block: str = ""
    """`market.market_block()`'s delimited market data (features/market-seo-20260924/spec.md, *What
    the proposal sees*), appended after the listing context. Empty when a
    search found nothing comparable -- the one case a proposal goes ahead
    without market data -- and then no block is sent at all."""


@dataclass(frozen=True)
class PhraseRationale:
    phrase: str
    intent: RationaleIntent
    reason: str
    used_in: tuple[RationaleField, ...]


@dataclass(frozen=True)
class ProposalWarning:
    message: str
    kind: WarningKind = "general"


@dataclass(frozen=True)
class SeoProposal:
    """`tags` keeps its ranked order: index position *is* the rank, so Best 13
    is simply `tags[:13]`, with no separate rank field to keep in sync."""

    titles: tuple[str, str, str]
    tags: tuple[str, ...]
    description_leads: tuple[str, str, str]
    rationale: tuple[PhraseRationale, ...]
    warnings: tuple[ProposalWarning, ...]
    observed_text: str


@dataclass(frozen=True)
class ProviderReadiness:
    ready: bool
    reason: str | None = None


@dataclass(frozen=True)
class RawProviderResult:
    provider: str
    raw_output: str


@dataclass(frozen=True)
class RepairContext:
    """A provider CLI keeps no session, so the one repair call carries the
    first call's unparsed output and every reason it failed validation."""

    prior_raw_output: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Deadline:
    """A monotonic point in time; the bare constructor is for tests that pin
    ``deadline_at``, and a run may inject one ``clock`` for every reader."""

    deadline_at: float = field(default=0.0)
    clock: Callable[[], float] | None = field(default=None, compare=False, repr=False)

    @classmethod
    def starting_now(cls, *, seconds: float, clock: Callable[[], float] | None = None) -> Deadline:
        return cls(deadline_at=(clock or time.monotonic)() + seconds, clock=clock)

    def _now(self) -> float:
        # Looked up per call, not bound at import, so a test can pin time.monotonic.
        return (self.clock or time.monotonic)()

    def remaining_seconds(self) -> float:
        """Never negative -- callers pass this straight to a subprocess
        timeout, and a negative timeout is not "expire immediately" to every
        API, it is undefined behaviour."""
        return max(0.0, self.deadline_at - self._now())

    @property
    def expired(self) -> bool:
        return self.remaining_seconds() <= 0.0

    def within(self, seconds: float) -> Deadline:
        """A deadline ``seconds`` from now, but never later than this one."""
        return Deadline(deadline_at=min(self._now() + seconds, self.deadline_at), clock=self.clock)


@dataclass(frozen=True)
class AiLimits:
    step_minutes: int = DEFAULT_STEP_LIMIT_MINUTES
    run_minutes: int = DEFAULT_RUN_LIMIT_MINUTES

    @classmethod
    def of(cls, settings: AiSettings) -> AiLimits:
        return cls(step_minutes=settings.step_limit_minutes, run_minutes=settings.run_limit_minutes)

    @property
    def step_seconds(self) -> float:
        return self.step_minutes * 60.0

    @property
    def run_seconds(self) -> float:
        return self.run_minutes * 60.0


@dataclass(frozen=True)
class RunBudget:
    limits: AiLimits
    deadline: Deadline

    @classmethod
    def starting_now(
        cls, limits: AiLimits | None = None, *, clock: Callable[[], float] | None = None
    ) -> RunBudget:
        limits = limits or AiLimits()
        return cls(limits, Deadline.starting_now(seconds=limits.run_seconds, clock=clock))

    def step(self) -> Deadline:
        return self.deadline.within(self.limits.step_seconds)
