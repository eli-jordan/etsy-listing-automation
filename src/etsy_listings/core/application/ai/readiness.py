"""Whether AI can run: for one listing, and for a batch created now
(features/market-seo-20260924/spec.md, *AI runs*; batch-creation spec,
*Design validation*; module-structure plan, PR 9).

The rules, their order and their wording are core's, so the **AI Mode**
button, ``POST /api/ai/runs`` and staging's *AI drafting can't run yet* all
say the same thing; the server only decides how each answer travels. So is
the choice of providers (:func:`default_ai_providers`), which a host passes
as a :data:`ProviderFactory` -- the seam tests replace with fakes, since CI
never calls a real Codex or Claude CLI.

Every check is a local probe -- a file's existence, a provider's fast
``--help``/``login status`` -- and changes nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel

from etsy_listings.core.ai.claude import ClaudeProvider
from etsy_listings.core.ai.codex import CodexProvider
from etsy_listings.core.ai.grok import GrokProvider
from etsy_listings.core.ai.providers import AiProvider
from etsy_listings.core.config.listing import Listing
from etsy_listings.core.workspace.facts import WorkspaceFacts
from etsy_listings.core.workspace.workspace import Workspace

ProviderFactory = Callable[[Workspace], Sequence[AiProvider]]
"""The providers to ask, in order. Called afresh for every readiness check
and every run, since a provider's own ``readiness()`` can change between
calls (the CLI signed out mid-session, for instance)."""


def default_ai_providers(workspace: Workspace) -> Sequence[AiProvider]:
    """Codex, then Claude, then Grok. A recognised unavailable failure
    falls through, so a usage limit on the first two still reaches Grok.
    Freshly constructed per call: readiness is re-checked every time, and
    there is no warm connection to hold onto.

    No prompt file is handed over: which prose a request is built from is
    the request's business, not the CLI's (``ai/models.py.ProviderTask``),
    so "a missing prompt file means not ready" lives only here, where the
    answer can name *which* file.
    """
    return (
        CodexProvider(workspace_root=workspace.root),
        ClaudeProvider(workspace_root=workspace.root),
        GrokProvider(workspace_root=workspace.root),
    )


def unready_reason(
    workspace: Workspace,
    listing: Listing,
    providers: Sequence[AiProvider],
    *,
    draft_brief: bool,
) -> str | None:
    """Why an AI run may not start for this listing, or ``None`` when it may.

    Checked in the order a seller would most usefully hear about them: what
    *this* listing is missing before what the local machine's provider
    tooling is missing, since the former is fixed by editing the listing and
    the latter is not the listing's to fix at all.

    A design, a brief, a usable garment profile (query extraction needs its
    item type), ``prompts/seo.md`` and ``prompts/market-queries.md``, and a
    ready provider. An empty brief is allowed only when ``draft_brief`` is
    true, and then ``prompts/brief.md`` is needed too.

    The listing itself being saved is the caller's to check first.
    """
    drafting = draft_brief and not listing.brief.strip()
    if not listing.design:
        return "the listing has no selected design"
    if not listing.brief.strip() and not drafting:
        return "the listing brief is empty"
    if WorkspaceFacts.gather(workspace).garment_profile(listing.garment_profile) is None:
        return "the listing has no usable garment profile"
    prompt_file = missing_prompt(workspace, draft_brief=drafting)
    if prompt_file is not None:
        return f"{prompt_file} is missing; run `etsy-listings setup` to seed it"
    unready = provider_problem(providers)
    if unready is not None:
        return f"no AI provider is ready ({unready})"
    return None


def missing_prompt(workspace: Workspace, *, draft_brief: bool) -> Path | None:
    """The first prompt file a run needs that is not there: ``seo.md`` and
    ``market-queries.md`` always, ``brief.md`` when the run drafts."""
    prompts = [workspace.seo_prompt_file(), workspace.market_queries_prompt_file()]
    if draft_brief:
        prompts.append(workspace.brief_prompt_file())
    return next((prompt for prompt in prompts if not prompt.is_file()), None)


def provider_problem(providers: Sequence[AiProvider]) -> str | None:
    """``None`` when some provider is ready, else every provider's reason."""
    checks = [provider.readiness() for provider in providers]
    if any(check.ready for check in checks):
        return None
    reasons = "; ".join(check.reason for check in checks if check.reason)
    return reasons or "no provider is configured"


class AiReadinessBlock(BaseModel):
    """Why a batch could not draft if it were created now (spec, *Design
    validation*; ``staging.note.md``): the sentence after *AI drafting can't
    run yet.*, and what to do about it. Transport-independent, so it is the
    staging detail's ``ai_blocked`` as it stands."""

    message: str
    remedy: str


SETUP_REMEDY = "Add one in Setup, then come back. Your staging is kept."


def batch_blocked(
    workspace: Workspace, providers: Sequence[AiProvider], *, has_market: bool
) -> AiReadinessBlock | None:
    """Whether a batch created now could draft: every prompt a drafting run
    reads, a ready provider -- :func:`unready_reason`'s own two checks -- and
    Etsy market access, which a manual run only finds missing once it
    reaches research. ``None`` when all three are there; the wording is
    ``staging.note.md``'s."""
    prompt_file = missing_prompt(workspace, draft_brief=True)
    if prompt_file is not None:
        shown = prompt_file.relative_to(workspace.root).as_posix()
        return AiReadinessBlock(
            message=f"{shown} is missing.",
            remedy="Run `etsy-listings setup` to seed it, then come back. Your staging is kept.",
        )
    if provider_problem(providers) is not None:
        return AiReadinessBlock(message="No AI provider is ready.", remedy=SETUP_REMEDY)
    if not has_market:
        return AiReadinessBlock(
            message="Etsy market access isn't set up.",
            remedy="Add the Etsy app key in Setup, then come back. Your staging is kept.",
        )
    return None
