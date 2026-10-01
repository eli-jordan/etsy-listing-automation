"""AI Mode's readiness endpoint, the market snapshot the top listings panel
reads, and the cached proposal (AI SEO implementation plan, PR5;
features/market-seo-20260924/spec.md, *AI runs*; market-seo implementation
plan, PR 8).

```
GET /api/listings/{name}/ai-seo/readiness -> SeoReadinessResponse
GET /api/listings/{name}/market -> MarketSnapshot | 404
GET /api/listings/{name}/proposal -> ListingProposal | 404
PATCH /api/listings/{name}/proposal/resolution -> ListingProposal | 404 | 409
```

Generation itself is an AI run (``core/application/ai/``, served by
``server/api/airuns.py``): the brief, market research and the proposal as one
run per listing, on its own thread, reattachable and cancellable. The rules a
run is refused by, which the **AI Mode** button is lit by, are core's
(``core/application/ai/readiness.py``), so the button is lit exactly when
``POST /api/ai/runs`` would accept the run the click starts.
"""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import APIRouter, HTTPException, Request

from etsy_listings.core.ai.listing_inputs import ListingAiInputs
from etsy_listings.core.ai.proposals import (
    ProposalReplacedError,
    ProposalStore,
)
from etsy_listings.core.ai.providers import AiProvider
from etsy_listings.core.application.ai.readiness import unready_reason
from etsy_listings.core.market import snapshot as market_snapshot
from etsy_listings.core.market.snapshot import MarketSnapshot
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.listings import Existing
from etsy_listings.server.api.schemas import (
    ListingProposal,
    ProposalResolutionPatch,
    SeoReadinessResponse,
)

router = APIRouter(prefix="/api/listings", tags=["ai-seo"])


def _providers(request: Request, workspace: Workspace) -> Sequence[AiProvider]:
    factory = request.app.state.seo_provider_factory
    result: Sequence[AiProvider] = factory(workspace)
    return result


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
    empty, so this is ``POST /api/ai/runs`` with ``draft_brief=true``. A lit
    button is one the server will not refuse. Read-only.
    """
    if request.app.state.ai_run_registry.deploying(target.name):
        return SeoReadinessResponse(ready=False, reason=DEPLOYING_REASON, deploying=True)
    if request.app.state.batch_queue.pending(target.name):
        return SeoReadinessResponse(ready=False, reason=BATCH_PENDING_REASON, batch_pending=True)
    listing = target.workspace.load_listing(target.name)
    providers = _providers(request, target.workspace)
    reason = unready_reason(target.workspace, listing, providers, draft_brief=True)
    return SeoReadinessResponse(ready=reason is None, reason=reason)


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
