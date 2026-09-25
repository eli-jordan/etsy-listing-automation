"""Saved-listing AI readiness and request-scoped generation endpoints (AI
SEO implementation plan, PR5; PRD 68 for the brief).

```
GET  /api/listings/{name}/ai-seo/readiness  -> SeoReadinessResponse
POST /api/listings/{name}/ai-seo/proposal   -> SeoProposalResponse  | 409/499/502/503
POST /api/ai/design-brief                   -> DesignBriefResponse  | 409/499/502/503
```

The brief endpoint is the older two's sibling in every respect that matters
here -- same providers, same deadline, same disconnect-cancellation, same
"nothing is written to a workspace file" rule. It differs in two ways, and
both follow from the same fact: a brief is about a *design*, not a listing.

So it is **not** a per-listing route. A seller creating a listing attaches
the design before naming it, and that is precisely when the brief is wanted
(PRD 68); a route under `/api/listings/{name}` could only answer 404 at that
moment. It takes the design and the garment profile directly instead, and
needs nothing on disk.

And a seller does something different with the answer: the browser writes a
drafted brief into the ordinary Brief field through the existing autosave
path, where a proposal's three suggestions instead wait for a per-field
choice. Which is to say the *model* still never writes `listing.yaml`; the
editor does, exactly as it does when a human types.

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
may run at all (:func:`readiness`), refusing a second concurrent request
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
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from etsy_listings.ai.brief import BriefRequest
from etsy_listings.ai.claude import ClaudeProvider
from etsy_listings.ai.codex import CodexProvider
from etsy_listings.ai.errors import (
    ProviderCancelledError,
    SeoAllProvidersUnavailableError,
    SeoTryAgainError,
)
from etsy_listings.ai.models import GarmentContext, SeoProposal, SeoRequest
from etsy_listings.ai.orchestrator import generate_brief, generate_proposal
from etsy_listings.ai.providers import AiProvider
from etsy_listings.config.garment_profile import GarmentProfile
from etsy_listings.config.listing import Listing
from etsy_listings.ui.api.listings import Existing
from etsy_listings.ui.api.schemas import (
    DesignBriefRequest,
    DesignBriefResponse,
    SeoProposalResponse,
    SeoProposalSnapshot,
    SeoRationaleEntry,
    SeoReadinessResponse,
    SeoWarningEntry,
)
from etsy_listings.workspace.facts import WorkspaceFacts
from etsy_listings.workspace.workspace import PathEscapesWorkspaceError, Workspace

router = APIRouter(prefix="/api/listings", tags=["ai-seo"])
brief_router = APIRouter(prefix="/api/ai", tags=["ai-brief"])
"""Drafting a brief is not about one listing (PRD 68), so it does not sit
under `/api/listings/{name}` and does not go through `Existing`. Same
module, because everything it does reach for -- the provider factory, the
active-request registry, the cancellation race, the error mapping -- is
right here."""

_PROPOSAL = "proposal"
_BRIEF = "brief"
"""The two kinds of request :class:`ActiveSeoRequests` tracks per listing.
Named constants rather than bare strings at four call sites, since a typo in
one of them would silently stop refusing a concurrent request -- a bug with
no symptom until two CLI subprocesses are writing over each other's answer."""

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
order decide. Anything not in this tuple falls back to the alphabetically
first key (`primary_design_image` below), so reordering the mapping cannot
change the image sent to a provider."""


class ActiveSeoRequests:
    """Which listings currently have an AI request in flight, in this
    process's memory only -- the settled "Concurrent requests" decision
    made data structure: "One request may run for each listing concurrently.
    A second request for the same listing is refused ... There is no
    durable queue or job record."

    Keyed by kind *and* listing, because there are two kinds of request now
    (PRD 68) and they are not rivals: drafting a brief is what *unblocks* a
    proposal, so the two never contend for the same work, and refusing a
    proposal because a brief is in flight would break the automatic chain on
    its very first step. Two of the same kind for one listing is still
    refused, which is the rule the decision was actually about.

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
        self._active: set[tuple[str, str]] = set()

    def begin(self, kind: str, name: str) -> bool:
        """Claim ``kind`` for ``name``; ``False`` if it was already claimed."""
        with self._lock:
            if (kind, name) in self._active:
                return False
            self._active.add((kind, name))
            return True

    def end(self, kind: str, name: str) -> None:
        """Release ``kind`` for ``name``. Safe to call even if :meth:`begin`
        was never called for it (never happens in practice, but a bare
        `.remove` would turn a bug into a `KeyError` masking the original
        one)."""
        with self._lock:
            self._active.discard((kind, name))


AiProviderFactory = Callable[[Workspace], Sequence[AiProvider]]
"""`create_app`'s injection seam for this module, the same shape
`ui/runs/executor.py.ContextFactory` already is for the runs executor: a
real server passes none and gets :func:`default_seo_providers`, a test
passes a factory that returns `FakeAiProvider` doubles instead. Per-request,
not per-app -- called fresh on every readiness check and every proposal
request, since a provider's own `readiness()` can change between calls
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
    prompt file means not ready" now lives only in :func:`readiness` and
    :func:`seller_prompt`, where the answer can name *which* file.
    """
    return (
        CodexProvider(workspace_root=workspace.root),
        ClaudeProvider(workspace_root=workspace.root),
    )


def _providers(request: Request, workspace: Workspace) -> Sequence[AiProvider]:
    factory = request.app.state.seo_provider_factory
    result: Sequence[AiProvider] = factory(workspace)
    return result


def _workspace(request: Request) -> Workspace:
    """The workspace this server was started on. `ui/api/listings.py` reads
    it the same way; this module's other two endpoints get it through
    `Existing`, which a listing-independent route has no business asking
    for."""
    workspace: Workspace = request.app.state.workspace
    return workspace


def _active_requests(request: Request) -> ActiveSeoRequests:
    registry: ActiveSeoRequests = request.app.state.seo_active_requests
    return registry


def primary_design_image(workspace: Workspace, name: str, listing: Listing) -> Path:
    listing_dir = workspace.listing_dir(name)
    key = next((k for k in _PREFERRED_DESIGN_KEYS if k in listing.design), min(listing.design))
    return workspace.resolve(listing.design[key], relative_to=listing_dir)


def readiness(
    workspace: Workspace,
    listing: Listing,
    providers: Sequence[AiProvider],
    *,
    draft_brief: bool | None = None,
) -> SeoReadinessResponse:
    """Every prerequisite the settled "Entry point" decision names, checked
    in the order a seller would most usefully hear about them: what *this*
    listing is missing before what the local machine's provider tooling is
    missing, since the former is fixed by editing the listing and the
    latter is not this request's to fix at all.

    ``draft_brief`` left ``None`` is the (retiring) proposal endpoint's rule
    set. A ``bool`` is an AI run's, and so the AI Mode button's
    (market-seo.md, *AI runs*): the same checks plus a usable garment
    profile, which query extraction needs for the item type, and
    ``prompts/market-queries.md``. An empty brief is allowed only when
    ``draft_brief`` is true, and then ``prompts/brief.md`` is needed.

    The listing itself already being saved is `target`'s job (`listings.py`)
    -- reaching this function at all already proves that, via the 404 every
    other per-listing endpoint in this module goes through the same way.
    """
    run = draft_brief is not None
    drafting = bool(draft_brief) and not listing.brief.strip()
    if not listing.design:
        return SeoReadinessResponse(ready=False, reason="the listing has no selected design")
    if not listing.brief.strip() and not drafting:
        return SeoReadinessResponse(ready=False, reason="the listing brief is empty")
    if run and WorkspaceFacts.gather(workspace).garment_profile(listing.garment_profile) is None:
        return SeoReadinessResponse(ready=False, reason="the listing has no usable garment profile")
    prompts = [workspace.seo_prompt_file()]
    if run:
        prompts.append(workspace.market_queries_prompt_file())
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
    return build_seo_request(workspace, name, listing, profile)


def build_seo_request(
    workspace: Workspace,
    name: str,
    listing: Listing,
    profile: GarmentProfile,
    *,
    market_block: str = "",
) -> SeoRequest:
    """:func:`_build_request` once the garment profile is known, with the
    AI run's market-data block (``""`` is none)."""
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


def _build_brief_request(workspace: Workspace, asked: DesignBriefRequest) -> BriefRequest:
    """The one input a drafted brief has: the design image.

    Checked rather than trusted, because it arrives from a browser. The path
    goes through `Workspace.resolve`, which refuses anything outside the
    workspace, and then has to exist -- a provider handed a missing image
    describes nothing, and says so confidently.
    """
    try:
        design_image = workspace.resolve(asked.design, relative_to=workspace.root)
    except PathEscapesWorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not design_image.is_file():
        raise HTTPException(status_code=409, detail=f"no design file at {asked.design!r}")
    return BriefRequest(design_image=design_image)


async def generate_with_cancellation[Result](
    generate: Callable[[threading.Event], Result],
    *,
    is_disconnected: Callable[[], Awaitable[bool]],
    poll_interval: float = _DISCONNECT_POLL_SECONDS,
) -> Result:
    """Run one blocking generation call off the event loop,
        racing it against ``is_disconnected`` reporting the browser is gone
        (implementation plan, PR5 item 3; the settled "Cancellation" decision).

        Generation is a plain blocking call -- ultimately a subprocess
        `communicate()` inside `ai/process.py.run_managed` -- so it runs on
        `loop.run_in_executor`'s default thread pool exactly the way
        `ui/api/runs.py`'s SSE bridge already runs its own blocking wait off the
        event loop, and for the same reason: nothing here can `await` a signal
        the blocking call would notice on its own.

    ``generate`` is handed the one `threading.Event` this function owns and
        returns whatever that generation produces -- a `SeoProposal` or a
        `DesignBrief`. Taking the call rather than a request and a provider list
        is what lets both endpoints share one cancellation implementation
        instead of two that could drift apart on the detail that matters most
        (whether the subprocess tree actually dies).

        ``is_disconnected`` takes a bare async callable -- `Request.is_disconnected`
        itself, at both real call sites below -- rather than a `Request`, so this
        function's own behaviour (poll, set the shared cancel event, wait for the
        worker to actually stop) is exercised directly by a test with a trivial
        stub, with no FastAPI/Starlette transport in the loop pretending to model
        a dropped TCP connection it was never going to faithfully simulate
        in-process.

        Always awaits ``future`` to completion before returning, even after a
        disconnect is detected -- `run_managed` needs a moment to kill the
        process tree and let its worker thread notice, and awaiting here is what
        keeps that cleanup inside this request's lifetime instead of leaking an
        orphaned background task.
    """
    cancel_event = threading.Event()
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(None, lambda: generate(cancel_event))
    while not future.done():
        if await is_disconnected():
            cancel_event.set()
            break
        await asyncio.wait({future}, timeout=poll_interval)
    return await future


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
    always visible control. The button starts an AI run that never drafts
    the brief, so this is ``POST /api/ai/runs``'s own rule set for
    ``draft_brief=false``: a lit button is one the server will not refuse.
    Read-only: every check here, including each provider's own
    `readiness()`, is a local probe (a file's existence, a fast
    `--help`/`login status` subprocess) that changes nothing.
    """
    listing = target.workspace.load_listing(target.name)
    providers = _providers(request, target.workspace)
    return readiness(target.workspace, listing, providers, draft_brief=False)


@contextmanager
def _generation_errors() -> Iterator[None]:
    """Map everything one generation can raise onto the status codes the
    settled "Timeout and retries" outcomes describe.

    Both endpoints wrap their whole guarded region in this, so the mapping
    exists once: 503 when every provider was recognised-unavailable, 502 for
    everything else the plan calls "Try again", and 499 for a cancellation.
    There is usually nobody left to receive a 499 -- the browser is gone,
    that being the definition -- but the request must still resolve to
    *something* so the coroutine, and the process it was managing, both end
    cleanly.

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
    ``{"detail": ...}`` JSON shape every other status code here uses, and
    the frontend should not have to special-case one endpoint's error body.
    ``HTTPException`` is re-raised untouched first, since the request
    builders raise those directly (the "no usable garment profile" 409) and
    one must reach the client as itself rather than folded into a 502.
    """
    try:
        yield
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


def read_seller_prompt(path: Path) -> str:
    """The seller's own prompt text, or the 409 that names the file it could
    not read.

    Both adapters used to answer this as *provider* unreadiness, which said
    "codex is not ready" about a file that has nothing to do with codex.
    Reading it here also means a prompt edited between the readiness check
    and the request is the one actually used.
    """
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"{path} could not be read; run `etsy-listings setup` to seed it ({exc})",
        ) from exc


@router.post("/{name}/ai-seo/proposal", response_model=SeoProposalResponse)
async def request_seo_proposal(target: Existing, request: Request) -> SeoProposalResponse:
    """Run one complete AI Mode SEO request for this saved listing.

    Refuses with 409 for exactly two reasons: this listing does not meet
    :func:`readiness`'s prerequisites (re-checked here independently of
    whatever the client last saw from the readiness endpoint -- state can
    change between the two calls), or another proposal request for the same
    listing is already running (the settled "Concurrent requests" decision;
    a *different* listing's request, or this listing's brief draft, is never
    refused). :func:`_generation_errors` owns every other outcome.

    Returns only what PR5 item 4 permits: the validated proposal, the input
    snapshot, and expiry metadata. Nothing here is written to a workspace
    file, a lockfile, or any server-side cache -- ``proposal`` and
    ``seo_request`` fall out of scope the moment this function returns.
    """
    workspace, name = target.workspace, target.name
    listing = workspace.load_listing(name)
    providers = _providers(request, workspace)
    ready = readiness(workspace, listing, providers)
    if not ready.ready:
        raise HTTPException(status_code=409, detail=ready.reason)

    active = _active_requests(request)
    if not active.begin(_PROPOSAL, name):
        raise HTTPException(
            status_code=409,
            detail=f"a proposal request is already running for listing {name!r}",
        )
    try:
        with _generation_errors():
            seller_prompt = read_seller_prompt(workspace.seo_prompt_file())
            seo_request = _build_request(workspace, name, listing)
            snapshot = proposal_snapshot(workspace, name, listing, seo_request)
            proposal = await generate_with_cancellation(
                lambda cancel: generate_proposal(
                    seo_request, seller_prompt, providers, cancel_event=cancel
                ),
                is_disconnected=request.is_disconnected,
            )
    finally:
        active.end(_PROPOSAL, name)

    return proposal_response(proposal, snapshot)


@brief_router.post("/design-brief", response_model=DesignBriefResponse)
async def request_design_brief(asked: DesignBriefRequest, request: Request) -> DesignBriefResponse:
    """Draft a listing brief from a design image (PRD 68).

    The browser calls this by itself, once, the moment a design is attached
    to a listing whose brief is empty -- including a listing that has no name
    and no file yet, which is the ordinary case while one is being created.
    So every refusal here is one a caller nobody asked to call has to be able
    to live with silently, and the client's reason for calling is re-checked
    rather than trusted: the design has to resolve inside the workspace and
    exist, some provider has to be ready, and `prompts/brief.md` has to be
    readable. Nothing about the listing is asked for -- not its name, and not
    its garment profile, which is usually still unchosen at this point.

    It deliberately does *not* ask whether any brief is already filled in.
    There is no listing here to ask about, and the browser is the only thing
    that knows whether the seller has typed into the field since the request
    was armed.

    Never writes the drafted text anywhere. It is returned, the editor puts
    it in the ordinary Brief field, and autosave persists it exactly as it
    persists a typed one -- which is what keeps "the model never writes
    `listing.yaml`" true (PRD 4, as amended by PRD 68).
    """
    workspace = _workspace(request)
    providers = _providers(request, workspace)
    checks = [provider.readiness() for provider in providers]
    if not any(check.ready for check in checks):
        reasons = "; ".join(check.reason for check in checks if check.reason)
        detail = reasons or "no provider is configured"
        raise HTTPException(status_code=409, detail=f"no AI provider is ready ({detail})")

    # Keyed by the design rather than a listing, for the same reason the route
    # is: two editors drafting for the same artwork at once would be two CLI
    # subprocesses reading one image to produce one answer.
    active = _active_requests(request)
    if not active.begin(_BRIEF, asked.design):
        raise HTTPException(
            status_code=409,
            detail=f"a brief request is already running for design {asked.design!r}",
        )
    try:
        with _generation_errors():
            seller_prompt = read_seller_prompt(workspace.brief_prompt_file())
            brief_request = _build_brief_request(workspace, asked)
            drafted = await generate_with_cancellation(
                lambda cancel: generate_brief(
                    brief_request, seller_prompt, providers, cancel_event=cancel
                ),
                is_disconnected=request.is_disconnected,
            )
    finally:
        active.end(_BRIEF, asked.design)

    return DesignBriefResponse(brief=drafted.brief)
