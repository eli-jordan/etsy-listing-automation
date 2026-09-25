"""AI Mode's readiness endpoint, the market snapshot the top listings panel
reads, and the helpers AI runs build a proposal with (AI SEO implementation
plan, PR5; market-seo.md, *AI runs*; market-seo implementation plan, PR 8).

```
GET  /api/listings/{name}/ai-seo/readiness  -> SeoReadinessResponse
GET  /api/listings/{name}/market            -> MarketSnapshot | 404
```

Generation itself is an AI run (``ui/airuns/``, served by
``ui/api/airuns.py``): the brief, market research and the proposal as one
run per listing, on its own thread, reattachable and cancellable. The two
request-scoped generation endpoints that used to live here -- one for a
proposal, one for a drafted brief, each racing a blocking call against the
browser disconnecting -- were retired when the browser moved onto runs
(implementation plan, PR 6). What is left is what runs and the button share:

- :func:`readiness`, the rules a run is refused by, which this module's
  endpoint answers with for the **AI Mode** button (``draft_brief=False``:
  the button never drafts), so the button is lit exactly when ``POST
  /api/ai/runs`` would accept it;
- turning a saved `Listing` into the `SeoRequest` the orchestrator wants
  (:func:`build_seo_request`, :func:`primary_design_image`), and the
  proposal's frozen input snapshot and wire response
  (:func:`proposal_snapshot`, :func:`proposal_response`);
- the provider factory ``create_app`` injects (:data:`AiProviderFactory`),
  the seam tests replace with fakes. CI never calls a real Codex or Claude
  CLI, per PR4's own rule.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from etsy_listings.ai.claude import ClaudeProvider
from etsy_listings.ai.codex import CodexProvider
from etsy_listings.ai.models import GarmentContext, SeoProposal, SeoRequest
from etsy_listings.ai.providers import AiProvider
from etsy_listings.config.garment_profile import GarmentProfile
from etsy_listings.config.listing import Listing
from etsy_listings.market import snapshot as market_snapshot
from etsy_listings.market.snapshot import MarketSnapshot
from etsy_listings.ui.api.listings import Existing
from etsy_listings.ui.api.schemas import (
    SeoProposalResponse,
    SeoProposalSnapshot,
    SeoRationaleEntry,
    SeoReadinessResponse,
    SeoWarningEntry,
)
from etsy_listings.workspace.facts import WorkspaceFacts
from etsy_listings.workspace.workspace import Workspace

router = APIRouter(prefix="/api/listings", tags=["ai-seo"])

_PROPOSAL_TTL = timedelta(days=1)
"""The settled "Proposal persistence" decision: "Store unresolved proposals
only in browser local storage ... for one day." The server never stores
one; it only stamps ``expires_at`` so the browser does not have to compute
the retention window itself from a client clock alone."""

_PREFERRED_DESIGN_KEYS: tuple[str, ...] = ("default", "on-light", "on-dark")
"""Which artwork key becomes the one image a provider sees, when a listing's
design map carries more than one (PRD 30's ``on-light``/``on-dark`` split).
The provider is reading the design once, for SEO copy and OCR text, not
rendering it per colour -- there is no per-colour resolution to do here, only
a deterministic single pick. ``"default"`` covers the common single-artwork
case (`config/listing.py._coerce_design`'s own normalisation target);
``on-light`` is preferred over ``on-dark`` next only because it has to be
one of them, arbitrarily, and a fixed order beats letting `dict` iteration
order decide. Anything not in this tuple falls back to the alphabetically
first key (`primary_design_image` below), so reordering the mapping cannot
change the image sent to a provider."""


AiProviderFactory = Callable[[Workspace], Sequence[AiProvider]]
"""`create_app`'s injection seam for this module, the same shape
`ui/runs/executor.py.ContextFactory` already is for the runs executor: a
real server passes none and gets :func:`default_ai_providers`, a test
passes a factory that returns `FakeAiProvider` doubles instead. Per-request,
not per-app -- called fresh on every readiness check and every AI run,
since a provider's own `readiness()` can change between calls
(the CLI being signed out mid-session, for instance)."""


def default_ai_providers(workspace: Workspace) -> Sequence[AiProvider]:
    """Codex, then Claude (the settled "Providers" decision) -- the real
    adapters, freshly constructed per call since both are plain, cheap
    dataclasses with no state worth reusing across requests (readiness
    itself is re-checked every call; there is no warm connection to hold
    onto). `create_app`'s default; a test overrides it with a factory that
    returns `FakeAiProvider` doubles instead.

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
    )


def _providers(request: Request, workspace: Workspace) -> Sequence[AiProvider]:
    factory = request.app.state.seo_provider_factory
    result: Sequence[AiProvider] = factory(workspace)
    return result


def primary_design_image(workspace: Workspace, name: str, listing: Listing) -> Path:
    listing_dir = workspace.listing_dir(name)
    key = next((k for k in _PREFERRED_DESIGN_KEYS if k in listing.design), min(listing.design))
    return workspace.resolve(listing.design[key], relative_to=listing_dir)


def readiness(
    workspace: Workspace,
    listing: Listing,
    providers: Sequence[AiProvider],
    *,
    draft_brief: bool,
) -> SeoReadinessResponse:
    """Whether an AI run may start for this listing (market-seo.md, *AI
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
    prompts = [workspace.seo_prompt_file(), workspace.market_queries_prompt_file()]
    if drafting:
        prompts.append(workspace.brief_prompt_file())
    for prompt_file in prompts:
        if not prompt_file.is_file():
            return SeoReadinessResponse(
                ready=False,
                reason=f"{prompt_file} is missing; run `etsy-listings setup` to seed it",
            )
    checks = [provider.readiness() for provider in providers]
    if not any(check.ready for check in checks):
        reasons = "; ".join(check.reason for check in checks if check.reason)
        detail = reasons or "no provider is configured"
        return SeoReadinessResponse(ready=False, reason=f"no AI provider is ready ({detail})")
    return SeoReadinessResponse(ready=True)


def build_seo_request(
    workspace: Workspace,
    name: str,
    listing: Listing,
    profile: GarmentProfile,
    *,
    market_block: str = "",
) -> SeoRequest:
    """The submitted generation inputs (implementation plan, "Proposal and
    stale-state rules"), read from the saved listing and its garment profile
    -- never from a value the browser supplied -- with the AI run's
    market-data block (``""`` is none).

    ``product_type`` is the garment profile's blueprint title and
    ``etsy_category`` the listing's shop section: the closest facts a listing
    carries to the two the prompt asks for."""
    return SeoRequest(
        market_block=market_block,
        brief=listing.brief,
        product_type=profile.blueprint.display_title,
        etsy_category=listing.etsy.section or "",
        materials=tuple(profile.materials),
        colors=tuple(listing.colors),
        garment=GarmentContext(brand=profile.blueprint.brand, model=profile.blueprint.model),
        design_image=primary_design_image(workspace, name, listing),
    )


def proposal_snapshot(
    workspace: Workspace, name: str, listing: Listing, seo_request: SeoRequest
) -> SeoProposalSnapshot:
    """Freeze the saved inputs before the provider starts its long request."""
    return SeoProposalSnapshot(
        brief=seo_request.brief,
        product_type=seo_request.product_type,
        etsy_category=seo_request.etsy_category,
        materials=list(seo_request.materials),
        colors=list(seo_request.colors),
        garment_brand=seo_request.garment.brand,
        garment_model=seo_request.garment.model,
        garment_profile=listing.garment_profile,
        design=dict(listing.design),
        design_content_hash=workspace.design_content_hash(
            listing.design, listing_dir=workspace.listing_dir(name)
        ),
    )


def proposal_response(proposal: SeoProposal, snapshot: SeoProposalSnapshot) -> SeoProposalResponse:
    generated_at = datetime.now(UTC)
    return SeoProposalResponse(
        titles=list(proposal.titles),
        tags=list(proposal.tags),
        description_leads=list(proposal.description_leads),
        rationale=[
            SeoRationaleEntry(
                phrase=entry.phrase,
                intent=entry.intent,
                reason=entry.reason,
                used_in=list(entry.used_in),
            )
            for entry in proposal.rationale
        ],
        warnings=[
            SeoWarningEntry(message=warning.message, kind=warning.kind)
            for warning in proposal.warnings
        ],
        observed_text=proposal.observed_text,
        snapshot=snapshot,
        generated_at=generated_at,
        expires_at=generated_at + _PROPOSAL_TTL,
    )


@router.get("/{name}/ai-seo/readiness", response_model=SeoReadinessResponse)
def get_seo_readiness(target: Existing, request: Request) -> SeoReadinessResponse:
    """Whether the **AI Mode** button may start a run for this saved listing
    right now -- the call the frontend makes to decide whether to enable the
    always visible control. The button never drafts a brief, so this is
    ``POST /api/ai/runs``'s own rule set for ``draft_brief=false``: a lit
    button is one the server will not refuse. Read-only: every check here,
    including each provider's own `readiness()`, is a local probe (a file's
    existence, a fast `--help`/`login status` subprocess) that changes
    nothing.
    """
    listing = target.workspace.load_listing(target.name)
    providers = _providers(request, target.workspace)
    return readiness(target.workspace, listing, providers, draft_brief=False)


@router.get(
    "/{name}/market",
    response_model=MarketSnapshot,
    responses={404: {"description": "No such listing, or no market search for it yet"}},
)
def get_market_snapshot(target: Existing) -> MarketSnapshot:
    """The listing's latest market research, as the top listings panel shows
    it after a reload (market-seo.md, *UI*). Written only by an AI run whose
    search succeeded, so a failed run leaves the previous one here. 404 until
    the first search -- the panel is not rendered then -- and for a snapshot
    that no longer reads as one, which the next run replaces."""
    snapshot = market_snapshot.load(target.workspace, target.name)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"no market snapshot for {target.name!r}")
    return snapshot
