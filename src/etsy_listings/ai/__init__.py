"""Local AI Mode SEO proposals: request/proposal contracts, the packaged
default prompt, delimited-context prompt assembly, and hard validation (AI
SEO implementation plan, PR3).

This package intentionally stops short of a real provider. ``providers.py``
declares the narrow ``SeoProvider`` protocol the orchestration service (PR5)
will drive and ships only ``FakeSeoProvider`` -- the Codex and Claude CLI
adapters behind that protocol are PR4's job, and nothing here launches a
subprocess.

- ``models`` -- ``SeoRequest``, ``SeoProposal``, ``PhraseRationale``,
  ``ProposalWarning``, ``ProviderReadiness``, ``RawProviderResult``,
  ``Deadline``.
- ``prompt`` -- the packaged default ``seo.md``, ``seed_default_prompt`` (the
  setup seed operation), and ``build_prompt``/``build_repair_prompt``, which
  wrap a seller's plain prompt text in delimited JSON context and a response
  schema.
- ``validation`` -- ``validate_proposal``: normalize harmless formatting, then
  hard-validate exact counts, Etsy limits, uniqueness, and the agreed
  affiliation/content checks; trademark findings become warnings, never a
  refusal.
- ``providers`` -- the ``SeoProvider`` protocol and ``FakeSeoProvider``.
"""

from __future__ import annotations

from etsy_listings.ai.models import (
    Deadline,
    GarmentContext,
    PhraseRationale,
    ProposalWarning,
    ProviderReadiness,
    RawProviderResult,
    SeoProposal,
    SeoRequest,
)
from etsy_listings.ai.prompt import (
    build_prompt,
    build_repair_prompt,
    default_prompt_text,
    seed_default_prompt,
)
from etsy_listings.ai.providers import FakeSeoProvider, SeoProvider
from etsy_listings.ai.validation import ProposalValidationError, validate_proposal

__all__ = [
    "Deadline",
    "FakeSeoProvider",
    "GarmentContext",
    "PhraseRationale",
    "ProposalValidationError",
    "ProposalWarning",
    "ProviderReadiness",
    "RawProviderResult",
    "SeoProposal",
    "SeoProvider",
    "SeoRequest",
    "build_prompt",
    "build_repair_prompt",
    "default_prompt_text",
    "seed_default_prompt",
    "validate_proposal",
]
