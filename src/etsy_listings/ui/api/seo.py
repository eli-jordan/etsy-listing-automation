"""Saved-listing AI SEO readiness and request-scoped proposal endpoints (AI
SEO implementation plan, PR5).

```
GET  /api/listings/{name}/ai-seo/readiness  -> SeoReadinessResponse
POST /api/listings/{name}/ai-seo/proposal   -> SeoProposalResponse | 409/502/503
```

Deliberately **outside** `ui/runs` (item 5): a proposal request creates no
`Run`, no SQLite record, no lockfile, no workspace output, and no
server-side proposal cache. There is nothing here for a client to reattach
to -- a dropped connection means a dropped request, not a job someone can
poll for later, which is exactly the point: the settled "Concurrent
requests" decision gives this feature "no durable queue or job record" on
purpose, unlike `ui/runs`'s registry. What little state this module keeps
(:class:`ActiveSeoRequests`) is process memory only, is not a queue -- it
never orders or retries anything -- and is emptied by the same request that
filled it, in a ``finally`` block, whether that request succeeded, failed,
or was cancelled.

This module is the one place `ai/orchestrator.py.generate_proposal` is
driven against the real `CodexProvider`/`ClaudeProvider` adapters instead of
`FakeSeoProvider` -- everything upstream of that call (retry classification,
fallback order, the shared deadline, hard validation) already exists from
PR3/PR4 and is reused as-is; nothing here adds new AI-domain logic. What is
new is entirely the HTTP wiring around it: turning a `Listing` already on
disk into the `SeoRequest` the orchestrator wants, deciding whether AI Mode
may run at all (:func:`_readiness`), refusing a second concurrent request
for the same listing, and racing generation against the browser
disconnecting (:func:`generate_with_cancellation` -- the settled
"Cancellation" decision: "The browser aborts a request when its editor is
left or its connection closes; the backend terminates that subprocess
tree").

``seo_provider_factory`` on `ui/api/app.py.create_app` is the same
injection seam `context_factory` already is for `ui/runs`: a test hands
`create_app` a factory that returns `FakeSeoProvider` doubles, so this
whole module runs identically for a test as for a real deployment. CI never
calls a real Codex or Claude CLI, per PR4's own rule.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from etsy_listings.ai.claude import ClaudeProvider
from etsy_listings.ai.codex import CodexProvider
from etsy_listings.ai.errors import (
    ProviderCancelledError,
    SeoAllProvidersUnavailableError,
    SeoTryAgainError,
)
from etsy_listings.ai.models import GarmentContext, SeoProposal, SeoRequest
from etsy_listings.ai.orchestrator import generate_proposal
from etsy_listings.ai.providers import SeoProvider
from etsy_listings.config.listing import Listing
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
only in browser local storage ... for one day." This module never stores
one; it only stamps ``expires_at`` so a future frontend (PR7) does not have
to compute the retention window itself from a client clock alone."""

_DISCONNECT_POLL_SECONDS = 0.25
"""How often :func:`generate_with_cancellation` asks Starlette whether the
browser is still there. `ui/api/runs.py`'s SSE stream polls the
same `Request.is_disconnected()` at a comparable cadence (1 second there,
against an idle stream); this is shorter because a proposal request is a
single blocking call, not a long-lived stream, and cancelling it promptly
matters more than the poll's own negligible cost."""

_PREFERRED_DESIGN_KEYS: tuple[str, ...] = ("default", "on-light", "on-dark")
"""Which artwork key becomes the one image a provider sees, when a listing's
design map carries more than one (PRD 30's ``on-light``/``on-dark`` split).
The provider is reading the design once, for SEO copy and OCR text, not
rendering it per colour -- there is no per-colour resolution to do here, only
a deterministic single pick. ``"default"`` covers the common single-artwork
case (`config/listing.py._coerce_design`'s own normalisation target);
``on-light`` is preferred over ``on-dark`` next only because it has to be
one of them, arbitrarily, and a fixed order beats letting `dict` iteration
order decide. Anything not in this tuple falls back to the map's first key
(`_primary_design_image` below), so a listing that uses neither convention
still resolves to *something* rather than raising."""


class ActiveSeoRequests:
    """Which listings currently have a proposal request in flight, in this
    process's memory only -- the settled "Concurrent requests" decision
    made data structure: "One request may run for each listing concurrently.
    A second request for the same listing is refused ... There is no
    durable queue or job record."

    A plain `set` guarded by a `threading.Lock` rather than an `asyncio.Lock`
    because :meth:`begin`/:meth:`end` are called from the request coroutine
    directly (never awaited across, so there is no `await` between the check
    and the insert that a race could land in) but must still be safe against
    two different listings' requests overlapping on the event loop while
    each has its own `generate_with_cancellation` call running the actual
    generation on `loop.run_in_executor`'s worker thread pool.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: set[str] = set()

    def begin(self, name: str) -> bool:
        """Claim ``name``; ``False`` if it was already claimed."""
        with self._lock:
            if name in self._active:
                return False
            self._active.add(name)
            return True

    def end(self, name: str) -> None:
        """Release ``name``. Safe to call even if :meth:`begin` was never
        called for it (never happens in practice, but a bare `.remove` would
        turn a bug into a `KeyError` masking the original one)."""
        with self._lock:
            self._active.discard(name)


SeoProviderFactory = Callable[[Workspace], Sequence[SeoProvider]]
"""`create_app`'s injection seam for this module, the same shape
`ui/runs/executor.py.ContextFactory` already is for the runs executor: a
real server passes none and gets :func:`default_seo_providers`, a test
passes a factory that returns `FakeSeoProvider` doubles instead. Per-request,
not per-app -- called fresh on every readiness check and every proposal
request, since a provider's own `readiness()` can change between calls
(the CLI being signed out mid-session, for instance)."""


def default_seo_providers(workspace: Workspace) -> Sequence[SeoProvider]:
    """Codex, then Claude (the settled "Providers" decision) -- the real
    adapters, freshly constructed per call since both are plain, cheap
    dataclasses with no state worth reusing across requests (readiness
    itself is re-checked every call; there is no warm connection to hold
    onto). `create_app`'s default; a test overrides it with a factory that
    returns `FakeSeoProvider` doubles instead."""
    prompt_file = workspace.seo_prompt_file()
    return (
        CodexProvider(workspace_root=workspace.root, prompt_file=prompt_file),
        ClaudeProvider(workspace_root=workspace.root, prompt_file=prompt_file),
    )


def _providers(request: Request, workspace: Workspace) -> Sequence[SeoProvider]:
    factory = request.app.state.seo_provider_factory
    result: Sequence[SeoProvider] = factory(workspace)
    return result


def _active_requests(request: Request) -> ActiveSeoRequests:
    registry: ActiveSeoRequests = request.app.state.seo_active_requests
    return registry


def _primary_design_image(workspace: Workspace, name: str, listing: Listing) -> Path:
    listing_dir = workspace.listing_dir(name)
    keys = list(listing.design.keys())
    key = next((k for k in _PREFERRED_DESIGN_KEYS if k in keys), keys[0])
    return workspace.resolve(listing.design[key], relative_to=listing_dir)


def _readiness(
    workspace: Workspace, listing: Listing, providers: Sequence[SeoProvider]
) -> SeoReadinessResponse:
    """Every prerequisite the settled "Entry point" decision names, checked
    in the order a seller would most usefully hear about them: what *this*
    listing is missing before what the local machine's provider tooling is
    missing, since the former is fixed by editing the listing and the
    latter is not this request's to fix at all.

    The listing itself already being saved is `target`'s job (`listings.py`)
    -- reaching this function at all already proves that, via the 404 every
    other per-listing endpoint in this module goes through the same way.
    """
    if not listing.design:
        return SeoReadinessResponse(ready=False, reason="the listing has no selected design")
    if not listing.brief.strip():
        return SeoReadinessResponse(ready=False, reason="the listing brief is empty")
    prompt_file = workspace.seo_prompt_file()
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


def _build_request(workspace: Workspace, name: str, listing: Listing) -> SeoRequest:
    """The submitted generation inputs snapshot (implementation plan,
    "Proposal and stale-state rules"): listing brief, garment context, and
    the other editable listing facts relevant to SEO copy -- read fresh from
    the saved listing and its garment profile, never from a value the
    client supplied, since AI Mode's whole entry-point rule is that it only
    ever describes a *saved* listing (`docs/ui-listing-seo-interactions.md`
    section 1).

    ``product_type``/``etsy_category`` have no dedicated field anywhere in
    this codebase's domain model (`seo_prompt.md`'s drafted context asks for
    both; nothing between `Listing` and `GarmentProfile` was ever built to
    hold them under those names). The closest existing facts stand in:
    the garment profile's own descriptive blueprint title (falling back to
    "brand model" when a profile predates that field, the same fallback
    `BlueprintRef.__str__` already provides) for ``product_type``, and the
    listing's chosen Etsy section for ``etsy_category`` -- a shop section is
    not Etsy's own taxonomy category, but it is the one Etsy-facing
    classification fact a listing actually carries, and an empty string
    when neither is set costs the prompt nothing (`ai/prompt.py` treats
    both as plain descriptive context, not something it validates).
    """
    facts = WorkspaceFacts.gather(workspace)
    profile = facts.garment_profile(listing.garment_profile)
    if profile is None:
        raise HTTPException(
            status_code=409,
            detail=f"listing {name!r} has no usable garment profile {listing.garment_profile!r}",
        )
    return SeoRequest(
        brief=listing.brief,
        product_type=profile.blueprint.title or str(profile.blueprint),
        etsy_category=listing.etsy.section or "",
        materials=tuple(profile.materials),
        colors=tuple(listing.colors),
        garment=GarmentContext(brand=profile.blueprint.brand, model=profile.blueprint.model),
        design_image=_primary_design_image(workspace, name, listing),
    )


async def generate_with_cancellation(
    seo_request: SeoRequest,
    providers: Sequence[SeoProvider],
    *,
    is_disconnected: Callable[[], Awaitable[bool]],
    poll_interval: float = _DISCONNECT_POLL_SECONDS,
) -> SeoProposal:
    """Run `ai/orchestrator.py.generate_proposal` off the event loop,
    racing it against ``is_disconnected`` reporting the browser is gone
    (implementation plan, PR5 item 3; the settled "Cancellation" decision).

    Generation is a plain blocking call -- ultimately a subprocess
    `communicate()` inside `ai/process.py.run_managed` -- so it runs on
    `loop.run_in_executor`'s default thread pool exactly the way
    `ui/api/runs.py`'s SSE bridge already runs its own blocking wait off the
    event loop, and for the same reason: nothing here can `await` a signal
    the blocking call would notice on its own.

    ``is_disconnected`` takes a bare async callable -- `Request.is_disconnected`
    itself, at the one real call site (`request_seo_proposal` below) -- rather
    than a `Request`, so this function's own behaviour (poll, set the shared
    cancel event, wait for the worker to actually stop) is exercised directly
    by a test with a trivial stub, with no FastAPI/Starlette transport in the
    loop pretending to model a dropped TCP connection it was never going to
    faithfully simulate in-process.

    Always awaits ``future`` to completion before returning, even after a
    disconnect is detected -- `run_managed` needs a moment to kill the
    process tree and let its worker thread notice, and awaiting here is what
    keeps that cleanup inside this request's lifetime instead of leaking an
    orphaned background task.
    """
    cancel_event = threading.Event()
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(
        None,
        lambda: generate_proposal(seo_request, providers, cancel_event=cancel_event),
    )
    while not future.done():
        if await is_disconnected():
            cancel_event.set()
            break
        await asyncio.wait({future}, timeout=poll_interval)
    return await future


def _to_response(proposal: SeoProposal, seo_request: SeoRequest) -> SeoProposalResponse:
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
        snapshot=SeoProposalSnapshot(
            brief=seo_request.brief,
            product_type=seo_request.product_type,
            etsy_category=seo_request.etsy_category,
            materials=list(seo_request.materials),
            colors=list(seo_request.colors),
            garment_brand=seo_request.garment.brand,
            garment_model=seo_request.garment.model,
        ),
        generated_at=generated_at,
        expires_at=generated_at + _PROPOSAL_TTL,
    )


@router.get("/{name}/ai-seo/readiness", response_model=SeoReadinessResponse)
def get_seo_readiness(target: Existing, request: Request) -> SeoReadinessResponse:
    """Whether **AI Mode** may be offered for this saved listing right now
    -- the call the frontend makes to decide whether to enable the always
    visible control. Read-only: every check here, including each
    provider's own `readiness()`, is a local probe (a file's existence, a
    fast `--help`/`login status` subprocess) that changes nothing.
    """
    listing = target.workspace.load_listing(target.name)
    providers = _providers(request, target.workspace)
    return _readiness(target.workspace, listing, providers)


@router.post("/{name}/ai-seo/proposal", response_model=SeoProposalResponse)
async def request_seo_proposal(target: Existing, request: Request) -> SeoProposalResponse:
    """Run one complete AI Mode SEO request for this saved listing.

    Refuses with 409 for exactly two reasons: this listing does not meet
    :func:`_readiness`'s prerequisites (re-checked here independently of
    whatever the client last saw from the readiness endpoint -- state can
    change between the two calls), or another request for the same listing
    is already running (the settled "Concurrent requests" decision; a
    *different* listing's request is never refused). Every failure the
    orchestrator itself can raise maps onto the settled "Timeout and
    retries" outcomes: 503 when every provider was recognised-unavailable,
    502 for everything else the plan calls "Try again". A cancellation
    (browser disconnect) answers 499 -- there is usually nobody left to
    receive it, but the request must still resolve to *something* so this
    coroutine, and the process it was managing, both end cleanly.

    The final ``except Exception`` is a deliberate catch-all, not a
    swallow-and-hope: everything above it is a recognised
    `~etsy_listings.ai.errors.SeoGenerationError` outcome the plan already
    names, but `ai/process.py.run_managed` can also raise a plain
    `CliProcessError` (`subprocess.Popen` itself failing to launch a
    provider's CLI -- e.g. a binary readiness confirmed present and then
    removed before this call), and any adapter bug is, by definition,
    something this module cannot enumerate in advance. Neither may leave
    FastAPI's own unhandled-exception path to answer: that path is a
    plain-text "Internal Server Error", not this module's
    ``{"detail": ...}`` JSON shape every other status code here uses, and a
    future frontend (PR7) should not have to special-case one endpoint's
    error body. ``HTTPException`` is re-raised untouched first, since
    :func:`_build_request` raises one of those directly (the "no usable
    garment profile" 409) and it must reach the client as itself, not get
    folded into a 502.

    Returns only what item 4 permits: the validated proposal, the input
    snapshot, and expiry metadata. Nothing here is written to a workspace
    file, a lockfile, or any server-side cache -- ``proposal`` and
    ``seo_request`` fall out of scope the moment this function returns.
    """
    workspace, name = target.workspace, target.name
    listing = workspace.load_listing(name)
    providers = _providers(request, workspace)
    readiness = _readiness(workspace, listing, providers)
    if not readiness.ready:
        raise HTTPException(status_code=409, detail=readiness.reason)

    active = _active_requests(request)
    if not active.begin(name):
        raise HTTPException(
            status_code=409,
            detail=f"a proposal request is already running for listing {name!r}",
        )
    try:
        seo_request = _build_request(workspace, name, listing)
        proposal = await generate_with_cancellation(
            seo_request, providers, is_disconnected=request.is_disconnected
        )
    except ProviderCancelledError as exc:
        raise HTTPException(status_code=499, detail=str(exc)) from exc
    except SeoAllProvidersUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SeoTryAgainError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        active.end(name)

    return _to_response(proposal, seo_request)
