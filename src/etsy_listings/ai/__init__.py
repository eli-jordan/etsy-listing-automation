"""Local AI Mode: request/task contracts, the two packaged default prompts,
delimited-context prompt assembly, hard validation, and the local
Codex/Claude CLI adapters behind `AiProvider` (AI SEO implementation plan,
PR3 and PR4; PRD 68 for brief drafting).

Two features, one machine. **SEO generation** produces a proposal a seller
reviews suggestion by suggestion; **brief drafting** produces the one input
that generation needs, from the design image alone. They differ only in the
prompt, the schema and the validation -- the provider adapters, the
Codex-then-Claude fallback, the one same-provider repair and the 60-second
deadline are shared, which is what `ProviderTask` exists to make possible.

- ``models`` -- ``ProviderTask``, ``SeoRequest``, ``SeoProposal``,
  ``PhraseRationale``, ``ProposalWarning``, ``ProviderReadiness``,
  ``RawProviderResult``, ``RepairContext``, ``Deadline``.
- ``prompt`` -- the packaged default ``seo.md``, ``seed_prompt`` (the setup
  seed operation, for either prompt file), ``build_task_prompt`` (the shared
  delimited-context wrapper) and ``build_seo_task``.
- ``brief`` -- everything drafting-specific in one small module:
  ``BriefRequest``, ``DesignBrief``, the packaged default ``brief.md``,
  ``build_brief_task`` and ``validate_brief``.
- ``validation`` -- ``validate_proposal``: normalize harmless formatting, then
  hard-validate exact counts, Etsy limits, uniqueness, and the agreed
  affiliation/content checks; trademark findings become warnings, never a
  refusal.
- ``providers`` -- the ``AiProvider`` protocol and ``FakeAiProvider``.
- ``codex``/``claude`` -- the real `CodexProvider`/`ClaudeProvider`
  adapters: a non-interactive, read-only, session-less CLI invocation each,
  behind the same `AiProvider` protocol (PR4). Neither reads a prompt file
  or knows which feature it is serving.
- ``orchestrator`` -- `run_task`, and the two entry points over it,
  `generate_proposal` and `generate_brief`.
- ``errors`` -- the exception hierarchy `orchestrator` and both adapters
  raise, and `classify_process_failure`, the availability classifier.
- ``process`` -- `run_managed`: cross-platform subprocess-tree launch and
  cleanup for timeouts, cancellation, and request disconnects (PR4).

`ui/api/seo.py` is where this package is wired to HTTP. CI never invokes a
real ``codex`` or ``claude`` binary: every adapter test replaces the
subprocess layer with a double, and every orchestrator test runs against
`FakeAiProvider`.
"""

from __future__ import annotations

from etsy_listings.ai.brief import (
    BRIEF_RESPONSE_SCHEMA,
    BriefRequest,
    BriefValidationError,
    DesignBrief,
    build_brief_task,
    default_brief_prompt_text,
    validate_brief,
)
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
    ProviderTask,
    RawProviderResult,
    RepairContext,
    SeoProposal,
    SeoRequest,
)
from etsy_listings.ai.orchestrator import generate_brief, generate_proposal, run_task
from etsy_listings.ai.process import CliProcessError, ProcessResult, run_managed
from etsy_listings.ai.prompt import (
    build_prompt,
    build_repair_prompt,
    build_seo_task,
    build_task_prompt,
    default_seo_prompt_text,
    seed_prompt,
)
from etsy_listings.ai.providers import AiProvider, FakeAiProvider
from etsy_listings.ai.validation import ProposalValidationError, validate_proposal

__all__ = [
    "BRIEF_RESPONSE_SCHEMA",
    "AiProvider",
    "BriefRequest",
    "BriefValidationError",
    "ClaudeProvider",
    "CliProcessError",
    "CodexProvider",
    "Deadline",
    "DesignBrief",
    "FakeAiProvider",
    "GarmentContext",
    "PhraseRationale",
    "ProcessResult",
    "ProposalValidationError",
    "ProposalWarning",
    "ProviderCancelledError",
    "ProviderGenerationError",
    "ProviderReadiness",
    "ProviderTask",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "RawProviderResult",
    "RepairContext",
    "SeoAllProvidersUnavailableError",
    "SeoDeadlineExceededError",
    "SeoGenerationError",
    "SeoProposal",
    "SeoRequest",
    "SeoTryAgainError",
    "build_brief_task",
    "build_prompt",
    "build_repair_prompt",
    "build_seo_task",
    "build_task_prompt",
    "classify_process_failure",
    "default_brief_prompt_text",
    "default_seo_prompt_text",
    "generate_brief",
    "generate_proposal",
    "run_managed",
    "run_task",
    "seed_prompt",
    "validate_brief",
    "validate_proposal",
]
