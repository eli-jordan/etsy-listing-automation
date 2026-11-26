"""Local AI Mode: SEO proposals, brief drafting and market-query extraction
through the local Codex, Claude and Grok CLIs behind one ``AiProvider``
contract, with provider fallback, one repair, and step and run budgets.

Withheld: ``discovery`` and ``host``, imported directly, and the private
``_windows_process`` and ``_posix_process``, behind ``run_managed``."""

from __future__ import annotations

from etsy_listings.core.ai.brief import (
    BRIEF_RESPONSE_SCHEMA,
    BriefRequest,
    BriefValidationError,
    DesignBrief,
    build_brief_task,
    default_brief_prompt_text,
    validate_brief,
)
from etsy_listings.core.ai.claude import ClaudeProvider
from etsy_listings.core.ai.codex import CodexProvider
from etsy_listings.core.ai.errors import (
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
from etsy_listings.core.ai.grok import GrokProvider
from etsy_listings.core.ai.listing_inputs import ListingAiInputs, PreparedSeo
from etsy_listings.core.ai.market_queries import (
    MARKET_QUERIES_RESPONSE_SCHEMA,
    MarketQueries,
    MarketQueriesRequest,
    MarketQueriesValidationError,
    build_market_queries_task,
    default_market_queries_prompt_text,
    validate_market_queries,
)
from etsy_listings.core.ai.models import (
    AiLimits,
    Deadline,
    GarmentContext,
    PhraseRationale,
    ProposalWarning,
    ProviderReadiness,
    ProviderTask,
    RawProviderResult,
    RepairContext,
    RunBudget,
    SeoProposal,
    SeoRequest,
)
from etsy_listings.core.ai.orchestrator import (
    generate_brief,
    generate_market_queries,
    generate_proposal,
    run_task,
)
from etsy_listings.core.ai.process import CliProcessError, ProcessResult, run_managed
from etsy_listings.core.ai.prompt import (
    build_prompt,
    build_repair_prompt,
    build_seo_task,
    build_task_prompt,
    default_seo_prompt_text,
    seed_prompt,
    sync_prompt,
)
from etsy_listings.core.ai.proposals import ProposalStore
from etsy_listings.core.ai.providers import AiProvider, FakeAiProvider
from etsy_listings.core.ai.validation import ProposalValidationError, validate_proposal

__all__ = [
    "BRIEF_RESPONSE_SCHEMA",
    "MARKET_QUERIES_RESPONSE_SCHEMA",
    "AiLimits",
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
    "GrokProvider",
    "ListingAiInputs",
    "MarketQueries",
    "MarketQueriesRequest",
    "MarketQueriesValidationError",
    "PhraseRationale",
    "PreparedSeo",
    "ProcessResult",
    "ProposalStore",
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
    "RunBudget",
    "SeoAllProvidersUnavailableError",
    "SeoDeadlineExceededError",
    "SeoGenerationError",
    "SeoProposal",
    "SeoRequest",
    "SeoTryAgainError",
    "build_brief_task",
    "build_market_queries_task",
    "build_prompt",
    "build_repair_prompt",
    "build_seo_task",
    "build_task_prompt",
    "classify_process_failure",
    "default_brief_prompt_text",
    "default_market_queries_prompt_text",
    "default_seo_prompt_text",
    "generate_brief",
    "generate_market_queries",
    "generate_proposal",
    "run_managed",
    "run_task",
    "seed_prompt",
    "sync_prompt",
    "validate_brief",
    "validate_market_queries",
    "validate_proposal",
]
