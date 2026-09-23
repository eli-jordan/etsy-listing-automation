"""Local AI Mode SEO proposals: request/proposal contracts, the packaged
default prompt, delimited-context prompt assembly, hard validation, and the
local Codex/Claude CLI adapters behind `SeoProvider` (AI SEO implementation
plan, PR3 and PR4).

- ``models`` -- ``SeoRequest``, ``SeoProposal``, ``PhraseRationale``,
  ``ProposalWarning``, ``ProviderReadiness``, ``RawProviderResult``,
  ``RepairContext``, ``Deadline``.
- ``prompt`` -- the packaged default ``seo.md``, ``seed_default_prompt`` (the
  setup seed operation), and ``build_prompt``/``build_repair_prompt``, which
  wrap a seller's plain prompt text in delimited JSON context and a response
  schema.
- ``validation`` -- ``validate_proposal``: normalize harmless formatting, then
  hard-validate exact counts, Etsy limits, uniqueness, and the agreed
  affiliation/content checks; trademark findings become warnings, never a
  refusal.
- ``providers`` -- the ``SeoProvider`` protocol and ``FakeSeoProvider``.
- ``codex``/``claude`` -- the real `CodexProvider`/`ClaudeProvider`
  adapters: a non-interactive, read-only, session-less CLI invocation each,
  behind the same `SeoProvider` protocol (PR4).
- ``orchestrator`` -- `generate_proposal`: the Codex-then-Claude chain, one
  same-provider repair, and the shared 60-second deadline (PR4).
- ``errors`` -- the exception hierarchy `orchestrator` and both adapters
  raise, and `classify_process_failure`, the availability classifier.
- ``process`` -- `run_managed`: cross-platform subprocess-tree launch and
  cleanup for timeouts, cancellation, and request disconnects (PR4).

Nothing in this package is wired to the UI or API yet -- that is PR5's job.
CI never invokes a real ``codex`` or ``claude`` binary: every adapter test
replaces the subprocess layer with a double (see `ai/codex.py`'s and
`ai/claude.py`'s own test suites), and every orchestrator test runs against
`FakeSeoProvider`.
"""

from __future__ import annotations

from etsy_listings.ai.claude import ClaudeProvider
from etsy_listings.ai.codex import CodexProvider
from etsy_listings.ai.errors import (
    ProviderCancelledError,
    ProviderGenerationError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    SeoAllProvidersUnavailableError,
    SeoDeadlineExceededError,
    SeoGenerationError,
    SeoTryAgainError,
    classify_process_failure,
)
from etsy_listings.ai.models import (
    Deadline,
    GarmentContext,
    PhraseRationale,
    ProposalWarning,
    ProviderReadiness,
    RawProviderResult,
    RepairContext,
    SeoProposal,
    SeoRequest,
)
from etsy_listings.ai.orchestrator import generate_proposal
from etsy_listings.ai.process import CliProcessError, ProcessResult, run_managed
from etsy_listings.ai.prompt import (
    build_prompt,
    build_repair_prompt,
    default_prompt_text,
    seed_default_prompt,
)
from etsy_listings.ai.providers import FakeSeoProvider, SeoProvider
from etsy_listings.ai.validation import ProposalValidationError, validate_proposal

__all__ = [
    "ClaudeProvider",
    "CliProcessError",
    "CodexProvider",
    "Deadline",
    "FakeSeoProvider",
    "GarmentContext",
    "PhraseRationale",
    "ProcessResult",
    "ProposalValidationError",
    "ProposalWarning",
    "ProviderCancelledError",
    "ProviderGenerationError",
    "ProviderReadiness",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "RawProviderResult",
    "RepairContext",
    "SeoAllProvidersUnavailableError",
    "SeoDeadlineExceededError",
    "SeoGenerationError",
    "SeoProposal",
    "SeoProvider",
    "SeoRequest",
    "SeoTryAgainError",
    "build_prompt",
    "build_repair_prompt",
    "classify_process_failure",
    "default_prompt_text",
    "generate_proposal",
    "run_managed",
    "seed_default_prompt",
    "validate_proposal",
]
