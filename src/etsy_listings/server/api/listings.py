"""Listings UI endpoints (features/listings-ui-20260915/spec.md): the dashboard/editor's
``/api/listings*`` surface, plus the read-only endpoints the editor's pickers
need (garment profiles, pricing plans, designs).

The HTTP adapter over ``core/application``'s listing operations
(module-structure plan, PR 6): ``listing_reads`` describes a listing or the
table, ``listing_edits`` merges an editor save, ``listing_creation`` names a
new one, ``listing_identity`` renames and deletes. Each owns its locking,
existence re-checks and the records that follow a listing. This module
decodes requests, passes in the process's coordinators (write locks, AI run
registry, Etsy state memo), maps refusals to status codes and projects
results onto the wire schemas.

Follows ``templates.py``'s conventions: a ``target()`` dependency for
existence-checking, ``Listing`` reused directly for the read/write body (the
wire shape *is* ``listing.yaml``), new API-only schemas only where the shape
genuinely differs, expected refusals caught locally and raised as
``HTTPException`` rather than relying on a shared handler.

A document that fails structural validation is not a status code: PATCH,
POST and the draft endpoints answer **200** with ``field_errors`` and the
listing as it was (or the empty draft), so the editor never branches on a
status to show inline validation. Only a *name* gets a status: not a path
segment is the 400 ``InvalidNameError`` becomes app-wide, unknown is 404,
taken is 409. Deleting a published listing is a 409 too (ADR-0035).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from etsy_listings.core import connections
from etsy_listings.core.ai.proposals import ProposalStore
from etsy_listings.core.application.ai.registry import AiRunRegistry
from etsy_listings.core.application.dependencies import EtsyStates
from etsy_listings.core.application.deploy.executor import ContextFactory
from etsy_listings.core.application.listing_creation import create_listing as create
from etsy_listings.core.application.listing_edits import edit_listing
from etsy_listings.core.application.listing_identity import delete_listing as delete
from etsy_listings.core.application.listing_identity import rename_listing as rename
from etsy_listings.core.application.listing_reads import (
    ListingRow,
    ListingView,
    PricedSize,
    describe_draft,
    listing_row,
    read_listing,
)
from etsy_listings.core.application.listing_reads import (
    list_listings as listing_rows,
)
from etsy_listings.core.application.pricing_plans import (
    load_candidate_pricing_plans,
    pricing_plan_options,
    pricing_plan_ref,
)
from etsy_listings.core.application.refusals import (
    ListingMissing,
    ListingNameTaken,
    PublishedListingDeletion,
)
from etsy_listings.core.application.workspace_locks import WorkspaceLocks
from etsy_listings.core.batches import BatchStore
from etsy_listings.core.clients.etsy.tokens import EtsyAuthError
from etsy_listings.core.clients.etsy.transport import EtsyApiError
from etsy_listings.core.config.listing import EMPTY_DRAFT, Listing
from etsy_listings.core.config.listing_validation import Issue as ValidationIssue
from etsy_listings.core.config.secrets import MissingCredentialError
from etsy_listings.core.engine.preview import lookup_preview
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.common_copy import CommonCopyError
from etsy_listings.core.workspace.facts import WorkspaceFacts
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.etsystate import etsy_states
from etsy_listings.server.api.schemas import (
    CommonCopySummary,
    CreateEtsySectionRequest,
    CreateListingRequest,
    DraftListingRequest,
    EtsySectionsResponse,
    EtsySectionSummary,
    GarmentProfileSummary,
    IssueCounts,
    ListingDesignSummary,
    ListingDetail,
    ListingSummary,
    PricingPlanSummary,
    RenameListingRequest,
    ResolvedPrice,
    WorkspaceSummary,
)
from etsy_listings.server.api.thumbnails import thumbnail_response

router = APIRouter(prefix="/api/listings", tags=["listings"])

# Distinct prefixes from `router` above (garment profiles/pricing plans/
# designs are not listings), so they get their own router rather than being
# force-fit under "/api/listings".
support_router = APIRouter(tags=["listings-support"])


def _workspace(request: Request) -> Workspace:
    workspace: Workspace = request.app.state.workspace
    return workspace


def _locks(request: Request) -> WorkspaceLocks:
    locks: WorkspaceLocks = request.app.state.workspace_locks
    return locks


def _proposals(request: Request) -> ProposalStore:
    store: ProposalStore = request.app.state.proposal_store
    return store


def _batch_store(request: Request) -> BatchStore:
    store: BatchStore = request.app.state.batch_store
    return store


def _ai_runs(request: Request) -> AiRunRegistry:
    runs: AiRunRegistry = request.app.state.ai.registry
    return runs


def _etsy_states(workspace: Workspace) -> EtsyStates:
    """Etsy's listing states through the process's short memo
    (``etsystate.py``), so an autosave burst costs one round trip."""

    def lookup(listing_ids: Sequence[int]) -> Mapping[int, str | None]:
        return etsy_states(workspace.root, listing_ids)

    return lookup


@dataclass(frozen=True)
class Target:
    workspace: Workspace
    name: str


def _require_listing(workspace: Workspace, name: str) -> None:
    if not workspace.listing_file(name).is_file():
        raise _not_found(ListingMissing(name))


def target(request: Request, name: str) -> Target:
    """404 before the handler runs for a listing that is not there. The
    operations re-check under the listing's lock once they hold it."""
    workspace = _workspace(request)
    _require_listing(workspace, name)
    return Target(workspace=workspace, name=name)


Existing = Annotated[Target, Depends(target)]


def _not_found(exc: ListingMissing) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


def _conflict(exc: ListingNameTaken | PublishedListingDeletion) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


def wire_prices(prices: Sequence[PricedSize]) -> list[ResolvedPrice]:
    """Resolved prices as the editor shows them, ``Money`` formatted as it
    prints itself (e.g. ``"249 NOK"``). Shared with listing templates."""
    return [ResolvedPrice(size=price.size, amount=str(price.amount)) for price in prices]


def _wire_issues(issues: Sequence[ValidationIssue]) -> list[dict[str, str]]:
    return [
        {"severity": i.severity, "tab": i.tab, "where": i.where, "message": i.message}
        for i in issues
    ]


def _sole_design_name(listing: Listing) -> str | None:
    """The one design's name, or ``None`` when there isn't one.

    ``Listing.design`` is artwork-key -> path, and a bare string normalises to
    a single ``default`` entry -- the common case, and the only one with a
    picture that stands for the whole listing. The stem is what
    ``GET /api/listing-designs/{name}/thumbnail`` takes, since
    ``workspace.design_file`` derives one fixed path per name.
    """
    if len(listing.design) != 1:
        return None
    return Path(next(iter(listing.design.values()))).stem


def _summary(row: ListingRow) -> ListingSummary:
    listing = row.listing
    return ListingSummary(
        name=row.name,
        garment_profile=listing.garment_profile if listing is not None else "",
        design=_sole_design_name(listing) if listing is not None else None,
        colour_count=len(listing.colors) if listing is not None else 0,
        status=row.status,
        issue_counts=IssueCounts(
            block=sum(1 for i in row.issues if i.severity == "block"),
            warn=sum(1 for i in row.issues if i.severity == "warn"),
        ),
        etsy_listing_id=row.etsy_listing_id,
        printify_product_id=row.printify_product_id,
        gestures=list(row.gestures),
    )


def _project(workspace: Workspace, view: ListingView) -> ListingDetail:
    profile = view.garment_profile
    return ListingDetail.model_validate(
        {
            **view.listing.model_dump(mode="json"),
            "name": view.name,
            "modified_at": view.modified_at,
            "status": view.status,
            "issues": _wire_issues(view.issues),
            "field_errors": view.field_errors,
            "gestures": list(view.gestures),
            "etsy_listing_id": view.etsy_listing_id,
            "printify_product_id": view.printify_product_id,
            "pricing_plan_name": view.pricing_plan_name,
            "resolved_prices": [p.model_dump() for p in wire_prices(view.resolved_prices)],
            "garment_materials": profile.materials if profile is not None else [],
            "garment_product_type": profile.blueprint.display_title
            if profile is not None
            else None,
            "garment_brand": profile.blueprint.brand if profile is not None else None,
            "garment_model": profile.blueprint.model if profile is not None else None,
            "description_composed": view.description_composed,
            "design_content_hash": view.design_content_hash,
        },
        context={"currency": workspace.defaults.etsy.currency},
    )


def _detail(
    workspace: Workspace, name: str, *, field_errors: dict[str, str] | None = None
) -> ListingDetail:
    try:
        view = read_listing(workspace, name, etsy_states=_etsy_states(workspace))
    except ListingMissing as exc:
        raise _not_found(exc) from exc
    if field_errors:
        view = dataclasses.replace(view, field_errors=field_errors)
    return _project(workspace, view)


def _describe_draft(workspace: Workspace, document: Mapping[str, Any]) -> ListingDetail:
    """A candidate with no name, written nowhere: incomplete is described as
    it stands, malformed is ``field_errors`` over the empty draft -- see
    :func:`~etsy_listings.core.application.listing_reads.describe_draft`."""
    return _project(workspace, describe_draft(workspace, document))


@router.get("", response_model=list[ListingSummary])
def list_listings(request: Request) -> list[ListingSummary]:
    """Every listing, with its status resolved in **one** Etsy round trip for
    the whole table rather than one per row."""
    workspace = _workspace(request)
    return [_summary(row) for row in listing_rows(workspace, etsy_states=_etsy_states(workspace))]


@router.get("/{name}", response_model=ListingDetail)
def get_listing(target: Existing) -> ListingDetail:
    return _detail(target.workspace, target.name)


@router.patch("/{name}", response_model=ListingDetail)
def patch_listing(target: Existing, body: dict[str, Any], request: Request) -> ListingDetail:
    """Merge the editor's slice into ``listing.yaml``. A merged document
    that will not validate writes nothing and answers 200 with
    ``field_errors`` beside the listing as it still is."""
    workspace, name = target.workspace, target.name
    try:
        refused = edit_listing(
            workspace, name, body, locks=_locks(request), batches=_batch_store(request)
        )
    except ListingMissing as exc:
        raise _not_found(exc) from exc
    return _detail(workspace, name, field_errors=refused.field_errors if refused else None)


@router.delete("/{name}", response_model=None)
def delete_listing(target: Existing, request: Request) -> ListingSummary | Response:
    """Delete from the listings table.

    No remotes: wiped, 204. Remotes: marked ``lifecycle: deleted``, answering
    with the row left pending. Published: 409 -- retire it instead. Confirm
    is the UI's. What goes with the listing either way is
    :func:`~etsy_listings.core.application.listing_identity.delete_listing`'s.
    """
    workspace, name = target.workspace, target.name
    try:
        deletion = delete(
            workspace,
            name,
            locks=_locks(request),
            batches=_batch_store(request),
            proposals=_proposals(request),
            ai_runs=_ai_runs(request),
            etsy_states=_etsy_states(workspace),
        )
    except ListingMissing as exc:
        raise _not_found(exc) from exc
    except PublishedListingDeletion as exc:
        raise _conflict(exc) from exc
    if deletion.wiped:
        return Response(status_code=204)
    return _summary(listing_row(workspace, name, etsy_state=deletion.etsy_state))


@router.post("", response_model=ListingDetail)
def create_listing(request: Request, body: CreateListingRequest) -> ListingDetail:
    """Naming a listing is what creates it.

    Mirrors PATCH exactly, one level up: a document that fails
    ``Listing.model_validate`` is a **200** carrying ``field_errors`` with
    nothing written. The two things a *name* can be wrong about keep their
    status codes instead -- not a single path segment is the 400, and
    already taken (the directory, not just ``listing.yaml``) is a 409.
    """
    workspace = _workspace(request)
    try:
        refused = create(workspace, body.name, body.document, locks=_locks(request))
    except ListingNameTaken as exc:
        raise _conflict(exc) from exc
    if refused is not None:
        return _describe_draft(workspace, body.document)
    return _detail(workspace, body.name)


@router.post("/{name}/rename", response_model=ListingDetail)
def rename_listing(target: Existing, body: RenameListingRequest, request: Request) -> ListingDetail:
    """Move a listing, whole, to a new name -- with everything keyed by it
    (:func:`~etsy_listings.core.application.listing_identity.rename_listing`).

    POST rather than PUT: the body is neither the listing nor its new
    representation, and a second call 404s. `POST /api/templates/{name}/kind` is
    the same shape.
    """
    try:
        rename(
            target.workspace,
            target.name,
            body.new_name,
            locks=_locks(request),
            batches=_batch_store(request),
            proposals=_proposals(request),
            ai_runs=_ai_runs(request),
        )
    except ListingMissing as exc:
        raise _not_found(exc) from exc
    except ListingNameTaken as exc:
        raise _conflict(exc) from exc
    return _detail(target.workspace, body.new_name)


def _preview_response(
    request: Request, target: Target, template: str, colour: str | None
) -> Response:
    """ADR-0040, ADR-0041: the preview a plan run already rendered for this scene, at its
    *current* hash. :func:`~etsy_listings.core.engine.preview.lookup_preview` owns
    the hash and the path; this is the HTTP adapter over it.
    """
    factory: ContextFactory = request.app.state.context_factory
    found = lookup_preview(factory(target.workspace, None), target.name, template, colour)
    if found.miss == "blocked":
        raise HTTPException(status_code=404, detail="this listing has no render state yet")
    if found.miss == "no_scene":
        where = f"template {template!r}" + (f", colour {colour!r}" if colour is not None else "")
        raise HTTPException(status_code=404, detail=f"no scene for {where}")
    if found.path is None or not found.path.is_file():
        raise HTTPException(status_code=404, detail="no preview rendered yet for this scene")
    return Response(
        content=found.path.read_bytes(),
        media_type="image/png",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/{name}/previews/{template}")
def listing_preview(target: Existing, template: str, request: Request) -> Response:
    """A ``multiple``/``single``-kind scene: no per-colour photo, so no
    colour segment (ADR-0014's rule, mirrored from ``render_file``)."""
    return _preview_response(request, target, template, None)


@router.get("/{name}/previews/{template}/{colour}")
def listing_preview_coloured(
    target: Existing, template: str, colour: str, request: Request
) -> Response:
    """A ``colour-matrix``-kind scene: one preview per colour."""
    return _preview_response(request, target, template, colour)


@support_router.get("/api/listing-draft", response_model=ListingDetail)
def listing_draft(request: Request) -> ListingDetail:
    """The listing `+ New listing` opens the editor on, before it has a name.

    There is no separate create *form* -- the editor itself is the form, and a
    listing is written the moment it is named and priced. What the editor needs
    first is a document to render, and inventing one in the browser would put
    the starting shape of a listing in two places, so the server hands over
    `EMPTY_DRAFT`: nothing chosen, nothing invented, and a block issue for each
    thing still to pick.

    ``name`` comes back empty, which is exactly the state the editor refuses to
    save in.
    """
    return _describe_draft(_workspace(request), EMPTY_DRAFT)


@support_router.post("/api/listing-draft", response_model=ListingDetail)
def describe_listing_draft(request: Request, body: DraftListingRequest) -> ListingDetail:
    """The same, for a candidate the editor has since edited. Writes nothing.

    The mount-time draft above answers once; this is what keeps the issues
    banner true for every edit made before the listing has a name. Without it
    the banner would still be saying "no colours enabled" about a listing whose
    colours were picked a minute ago -- and the banner is the only way an
    unsaved listing can be told what it is still missing.
    """
    return _describe_draft(_workspace(request), body.document)


@support_router.get("/api/garment-profiles", response_model=list[GarmentProfileSummary])
def list_garment_profiles(request: Request) -> list[GarmentProfileSummary]:
    facts = WorkspaceFacts.gather(_workspace(request))
    result = []
    for name in facts.garment_profile_names:
        profile = facts.garment_profile(name)
        if profile is None:
            continue
        result.append(
            GarmentProfileSummary(
                name=name,
                sizes=profile.sizes,
                materials=profile.materials,
                colors=profile.colors,
                preview_template=profile.preview_template,
            )
        )
    return result


@support_router.get("/api/pricing-plans", response_model=list[PricingPlanSummary])
def list_pricing_plans(request: Request, garment_profile: str = "") -> list[PricingPlanSummary]:
    """Every plan, each flagged for whether it was built for this garment.

    ``garment_profile`` is optional because a listing that has not chosen one
    yet has nothing to be compatible *with*: asking with an empty name says that
    honestly, and the editor then drops the "different garment" note rather than
    labelling every plan as differing from a garment nobody picked."""
    workspace = _workspace(request)
    options = pricing_plan_options(load_candidate_pricing_plans(workspace), garment_profile)
    return [
        PricingPlanSummary(
            name=option.path.stem,
            garment_profile=option.plan.garment_profile,
            compatible=option.compatible,
            ref=pricing_plan_ref(option.path, root=workspace.root),
        )
        for option in options
    ]


@support_router.get("/api/etsy/sections", response_model=EtsySectionsResponse)
def list_etsy_sections(request: Request) -> EtsySectionsResponse:
    """The live shop's sections, for the Details tab's Section dropdown.
    Unavailable (not a 500) for a workspace with no `shop_id` yet or no Etsy
    app key pair -- both ordinary states short of `setup`/`auth etsy`, where
    the frontend falls back to a plain text field. An available empty list is
    different: it lets a configured shop create its first section."""
    workspace = _workspace(request)
    shop_id = workspace.defaults.etsy.shop_id
    if shop_id is None:
        return EtsySectionsResponse(available=False, sections=[])
    client = connections.etsy_shop_client(workspace.root)
    if client is None:
        return EtsySectionsResponse(available=False, sections=[])
    try:
        sections = client.shop_sections(shop_id)
    except (EtsyApiError, EtsyAuthError, MissingCredentialError):
        return EtsySectionsResponse(available=False, sections=[])
    return EtsySectionsResponse(
        available=True,
        sections=[EtsySectionSummary(id=s.shop_section_id, title=s.title) for s in sections],
    )


@support_router.post("/api/etsy/sections", response_model=EtsySectionSummary)
def create_etsy_section(request: Request, body: CreateEtsySectionRequest) -> EtsySectionSummary:
    """Create a shop section from the Details tab's inline picker.

    Unlike the list beside it, creation is scoped and therefore goes through
    the signed-in Etsy client. The listing document is updated separately by
    the editor's normal autosave after this returns successfully.
    """
    workspace = _workspace(request)
    shop_id = workspace.defaults.etsy.shop_id
    if shop_id is None:
        raise HTTPException(
            status_code=409, detail="Configure an Etsy shop before adding a section."
        )
    client = connections.etsy_listing_client(workspace.root)
    if client is None:
        raise HTTPException(
            status_code=409, detail="Configure Etsy credentials before adding a section."
        )
    try:
        section = client.create_shop_section(shop_id, body.title)
    except (EtsyAuthError, MissingCredentialError) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except EtsyApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return EtsySectionSummary(id=section.shop_section_id, title=section.title)


@support_router.get("/api/common-copy", response_model=list[CommonCopySummary])
def list_common_copy(request: Request) -> list[CommonCopySummary]:
    """The Description tab's common-copy selector (AI SEO implementation
    plan, PR6): every reusable description body, with the title and summary
    its front matter carries, so the picker can show something readable
    rather than a bare filename.

    A file whose front matter will not parse is left out -- read-only, so
    there is nowhere here to report the problem, and offering it would only
    produce a pick that immediately fails to resolve. (A *stored* ref that
    fails to resolve still surfaces as a details-tab issue -- see
    `Workspace.resolve_description` -- this is only the list of things one
    could newly pick.)
    """
    workspace = _workspace(request)
    summaries: list[CommonCopySummary] = []
    for path in workspace.common_copy_files():
        ref = f"{layout.COMMON_COPY_DIR}/{path.name}"
        try:
            doc = workspace.load_common_copy(ref)
        except CommonCopyError:
            continue
        summaries.append(CommonCopySummary(ref=ref, title=doc.title, summary=doc.summary))
    return summaries


@support_router.get("/api/workspace", response_model=WorkspaceSummary)
def get_workspace(request: Request) -> WorkspaceSummary:
    workspace = _workspace(request)
    return WorkspaceSummary(
        shop_name=workspace.defaults.etsy.shop_name,
        storage_id=workspace.browser_storage_id(),
    )


@support_router.get("/api/listing-designs", response_model=list[ListingDesignSummary])
def list_listing_designs(request: Request) -> list[ListingDesignSummary]:
    workspace = _workspace(request)
    return [
        ListingDesignSummary(name=path.stem, file=f"designs/{path.name}")
        for path in workspace.design_files()
    ]


@support_router.get("/api/listing-designs/{name}/thumbnail")
def listing_design_thumbnail(request: Request, name: str) -> Response:
    """The artwork itself, downscaled -- what the listings table, its hover
    card and the editor's design strip all show.

    Distinct from ``designs.py``'s calibrator library for the same reason
    ``GET /api/listing-designs`` is: ``designs/`` holds artwork that ships,
    ``test-designs/`` holds calibration targets, and a listing's design is
    never one of the latter.

    An unusable *name* needs nothing here: ``InvalidNameError`` out of
    ``design_file`` becomes a 400 through the app-wide handler in ``app.py``.
    """
    workspace = _workspace(request)
    path = workspace.design_file(name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"no design {name!r}")
    return thumbnail_response(path)
