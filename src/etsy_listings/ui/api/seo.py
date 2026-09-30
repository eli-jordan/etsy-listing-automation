"""AI Mode's readiness endpoint, the market snapshot the top listings panel
reads, and the helpers AI runs build a proposal with (AI SEO implementation
plan, PR5; features/market-seo-20260924/spec.md, *AI runs*; market-seo implementation plan, PR 8).

```
GET /api/listings/{name}/ai-seo/readiness -> SeoReadinessResponse
GET /api/listings/{name}/market -> MarketSnapshot | 404
GET /api/listings/{name}/proposal -> ListingProposal | 404
PATCH /api/listings/{name}/proposal/resolution -> ListingProposal | 404 | 409
```

Generation itself is an AI run (``ui/airuns/``, served by
``ui/api/airuns.py``): the brief, market research and the proposal as one
run per listing, on its own thread, reattachable and cancellable. The two
request-scoped generation endpoints that used to live here -- one for a
proposal, one for a drafted brief, each racing a blocking call against the
browser disconnecting -- were retired when the browser moved onto runs
(implementation plan, PR 6). What is left is what runs and the button share:

- :func:`readiness`, the rules a run is refused by, which this module's
  endpoint answers with for the **AI Mode** button (``draft_brief=True``:
  an empty brief is drafted by that click), so the button is lit exactly
  when ``POST /api/ai/runs`` would accept the run the click starts;
- saved-listing preparation and proposal judgment live in ai/listing_inputs;
- the provider factory ``create_app`` injects (:data:`AiProviderFactory`),
  the seam tests replace with fakes. CI never calls a real Codex or Claude
  CLI, per PR4's own rule.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from etsy_listings.core.ai.claude import ClaudeProvider
from etsy_listings.core.ai.codex import CodexProvider
from etsy_listings.core.ai.grok import GrokProvider
from etsy_listings.core.ai.listing_inputs import ListingAiInputs
from etsy_listings.core.ai.proposals import (
    ProposalReplacedError,
    ProposalStore,
)
from etsy_listings.core.ai.providers import AiProvider
from etsy_listings.core.config.listing import Listing
from etsy_listings.core.market import snapshot as market_snapshot
from etsy_listings.core.market.snapshot import MarketSnapshot
from etsy_listings.core.workspace.facts import WorkspaceFacts
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.ui.api.listings import Existing
from etsy_listings.ui.api.schemas import (
    AiReadinessBlock,
    ListingProposal,
    ProposalResolutionPatch,
    SeoReadinessResponse,
)

router = APIRouter(prefix="/api/listings", tags=["ai-seo"])

AiProviderFactory = Callable[[Workspace], Sequence[AiProvider]]
"""`create_app`'s injection seam for this module, the same shape
`ui/runs/executor.py.ContextFactory` already is for the runs executor: a
real server passes none and gets :func:`default_ai_providers`, a test
passes a factory that returns `FakeAiProvider` doubles instead. Per-request,
not per-app -- called fresh on every readiness check and every AI run,
since a provider's own `readiness()` can change between calls
(the CLI being signed out mid-session, for instance)."""


def default_ai_providers(workspace: Workspace) -> Sequence[AiProvider]:
    """Codex, then Claude, then Grok. A recognised unavailable failure
    falls through, so a usage limit on the first two still reaches Grok.
    Freshly constructed per call: readiness is re-checked every time, and
    there is no warm connection to hold onto. `create_app`'s default; a
    test overrides it with a factory that returns `FakeAiProvider` doubles
    instead.

    No prompt file is handed over: an adapter no longer reads one, because
    which prose a request is built from is the request's business and not
    the CLI's (`ai/models.py.ProviderTask`). That also removes a rule this
    module and both adapters used to hold separate copies of -- "a missing
    prompt file means not ready" now lives only in :func:`readiness`, where
    the answer can name *which* file.
    """
    return (
        CodexProvider(workspace_root=workspace.root),
        ClaudeProvider(workspace_root=workspace.root),
        GrokProvider(workspace_root=workspace.root),
    )


def _providers(request: Request, workspace: Workspace) -> Sequence[AiProvider]:
    factory = request.app.state.seo_provider_factory
    result: Sequence[AiProvider] = factory(workspace)
    return result


def readiness(
    workspace: Workspace,
    listing: Listing,
    providers: Sequence[AiProvider],
    *,
    draft_brief: bool,
) -> SeoReadinessResponse:
    """Whether an AI run may start for this listing (features/market-seo-20260924/spec.md, *AI
    runs*), checked in the order a seller would most usefully hear about
    them: what *this* listing is missing before what the local machine's
    provider tooling is missing, since the former is fixed by editing the
    listing and the latter is not this request's to fix at all.

    A design, a brief, a usable garment profile (query extraction needs its
    item type), ``prompts/seo.md`` and ``prompts/market-queries.md``, and a
    ready provider. An empty brief is allowed only when ``draft_brief`` is
    true, and then ``prompts/brief.md`` is needed too.

    The listing itself already being saved is the caller's job -- both
    callers answer 404 before they get here.
    """
    drafting = draft_brief and not listing.brief.strip()
    if not listing.design:
        return SeoReadinessResponse(ready=False, reason="the listing has no selected design")
    if not listing.brief.strip() and not drafting:
        return SeoReadinessResponse(ready=False, reason="the listing brief is empty")
    if WorkspaceFacts.gather(workspace).garment_profile(listing.garment_profile) is None:
        return SeoReadinessResponse(ready=False, reason="the listing has no usable garment profile")
    prompt_file = missing_prompt(workspace, draft_brief=drafting)
    if prompt_file is not None:
        return SeoReadinessResponse(
            ready=False,
            reason=f"{prompt_file} is missing; run `etsy-listings setup` to seed it",
        )
    unready = provider_problem(providers)
    if unready is not None:
        return SeoReadinessResponse(ready=False, reason=f"no AI provider is ready ({unready})")
    return SeoReadinessResponse(ready=True)


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


SETUP_REMEDY = "Add one in Setup, then come back. Your staging is kept."


def batch_readiness(
    workspace: Workspace, providers: Sequence[AiProvider], *, has_market: bool
) -> AiReadinessBlock | None:
    """Whether a batch created now could draft (spec, *Design validation*):
    every prompt a drafting run reads, a ready provider -- :func:`readiness`'
    own two checks -- and Etsy market access, which a manual run only finds
    missing once it reaches research. ``None`` when all three are there;
    the wording is ``staging.note.md``'s."""
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


BATCH_PENDING_REASON = "This listing is drafting in a batch. AI Mode is back once that is done."
"""The editor's hint while a batch row owns the listing's AI (spec,
*Scheduling*: two runs must never own one listing)."""


DEPLOYING_REASON = "This listing is deploying. AI Mode is back once the deploy finishes."
"""The editor's hint while a UI plan or apply holds the listing (ADR-0050; UI doc
§8, *Deploying takes precedence over AI*)."""


def _proposals(request: Request) -> ProposalStore:
    store: ProposalStore = request.app.state.proposal_store
    return store


@router.get("/{name}/ai-seo/readiness", response_model=SeoReadinessResponse)
def get_seo_readiness(target: Existing, request: Request) -> SeoReadinessResponse:
    """Whether the **AI Mode** button may start a run for this saved listing
    right now -- the call the frontend makes to decide whether to enable the
    always visible control. The button drafts a brief when the saved one is
    empty, so this is ``POST /api/ai/runs`` with ``draft_brief=true``: an
    empty brief is allowed, and then ``prompts/brief.md`` is required. A
    filled brief skips drafting. A lit button is one the server will not
    refuse. Read-only: every check here, including each provider's own
    `readiness()`, is a local probe (a file's existence, a fast
    `--help`/`login status` subprocess) that changes nothing.
    """
    if request.app.state.ai_run_registry.deploying(target.name):
        return SeoReadinessResponse(ready=False, reason=DEPLOYING_REASON, deploying=True)
    if request.app.state.batch_queue.pending(target.name):
        return SeoReadinessResponse(ready=False, reason=BATCH_PENDING_REASON, batch_pending=True)
    listing = target.workspace.load_listing(target.name)
    providers = _providers(request, target.workspace)
    return readiness(target.workspace, listing, providers, draft_brief=True)


@router.get(
    "/{name}/market",
    response_model=MarketSnapshot,
    responses={404: {"description": "No such listing, or no market search for it yet"}},
)
def get_market_snapshot(target: Existing) -> MarketSnapshot:
    """The listing's latest market research, as the top listings panel shows
    it after a reload (features/market-seo-20260924/spec.md, *UI*). Written only by an AI run whose
    search succeeded, so a failed run leaves the previous one here. 404 until
    the first search -- the panel is not rendered then -- and for a snapshot
    that no longer reads as one, which the next run replaces."""
    snapshot = market_snapshot.load(target.workspace, target.name)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"no market snapshot for {target.name!r}")
    return snapshot


@router.get(
    "/{name}/proposal",
    response_model=ListingProposal,
    responses={404: {"description": "No such listing, or no proposal cached for it"}},
)
def get_listing_proposal(target: Existing, request: Request) -> ListingProposal:
    """The listing's latest AI SEO proposal (ADR-0049; spec, *Durable AI
    proposals*), with which sections were resolved and whether it has gone
    stale. Written by every AI run before it announces the proposal, so a
    reload, a server restart or a batch run all find it here."""
    record = _proposals(request).load(target.name)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no proposal for {target.name!r}")
    return ListingAiInputs.read(target.workspace, target.name).judge(record)


@router.patch(
    "/{name}/proposal/resolution",
    response_model=ListingProposal,
    responses={
        404: {"description": "No such listing, or no proposal cached for it"},
        409: {"description": "The proposal was regenerated since the page read it"},
    },
)
def resolve_listing_proposal(
    target: Existing, body: ProposalResolutionPatch, request: Request
) -> ListingProposal:
    """Record accepted or dismissed sections (spec, *Durable AI proposals*),
    so a resolved drawer does not reopen as new after a reload. The chosen
    value itself reaches ``listing.yaml`` through ordinary autosave; this
    records only that the section was dealt with. Under the listing's write
    lock, so a delete or rename cannot land between the read and the write
    and leave a record behind for a listing that is gone."""
    store = _proposals(request)
    with target.writing():
        try:
            record = store.resolve(
                target.name,
                generated_at=body.generated_at,
                title=body.title,
                tags=body.tags,
                lead=body.lead,
            )
        except ProposalReplacedError as exc:
            raise HTTPException(
                status_code=409, detail="this proposal was replaced by a newer one"
            ) from exc
    if record is None:
        raise HTTPException(status_code=404, detail=f"no proposal for {target.name!r}")
    return ListingAiInputs.read(target.workspace, target.name).judge(record)
