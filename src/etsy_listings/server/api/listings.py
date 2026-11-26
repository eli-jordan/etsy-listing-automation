from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import Response
from PIL import Image

from etsy_listings.core.application.ai.registry import AiRunRegistry
from etsy_listings.core.application.dependencies import ContextFactory, EtsyStates
from etsy_listings.core.application.listing_creation import create_listing as create
from etsy_listings.core.application.listing_designs import save_listing_design
from etsy_listings.core.application.listing_edits import edit_listing
from etsy_listings.core.application.listing_identity import delete_listing as delete
from etsy_listings.core.application.listing_identity import rename_listing as rename
from etsy_listings.core.application.listing_reads import (
    ListingRow,
    ListingView,
    PhaseTimer,
    describe_draft,
    listing_row,
    listing_scenes,
    read_listing,
)
from etsy_listings.core.application.listing_reads import (
    list_listings as listing_rows,
)
from etsy_listings.core.application.position_coverage import cover_listing_positions
from etsy_listings.core.application.pricing_plans import (
    load_candidate_pricing_plans,
    pricing_plan_options,
    pricing_plan_ref,
)
from etsy_listings.core.application.refusals import (
    ListingMissingError,
)
from etsy_listings.core.application.scene_previews import (
    SceneFrame,
    SceneLayers,
    layer_artwork,
    remembered_scene,
    remembered_scene_was_wrong,
    saved_scene,
)
from etsy_listings.core.application.scene_warming import SceneWarmer
from etsy_listings.core.clients.etsy.tokens import EtsyAuthError, EtsyRefreshBusyError
from etsy_listings.core.clients.etsy.transport import EtsyApiError
from etsy_listings.core.config.artwork import representative
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.config.listing import EMPTY_DRAFT, Listing
from etsy_listings.core.config.listing_validation import Issue as ValidationIssue
from etsy_listings.core.config.secrets import MissingCredentialError
from etsy_listings.core.engine.preview import lookup_preview
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.common_copy import CommonCopyError
from etsy_listings.core.workspace.facts import WorkspaceFacts
from etsy_listings.core.workspace.listing_documents import ListingDocuments
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api import app_state
from etsy_listings.server.api.editor_projections import garment_fields, wire_prices
from etsy_listings.server.api.etsystate import etsy_states
from etsy_listings.server.api.imagecache import LIVE_ARTWORK_EDGE, PREVIEW_IMAGES
from etsy_listings.server.api.scene_responses import ScenePreviewQuery, scene_response
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
    SceneCheckResponse,
    WorkspaceSummary,
)
from etsy_listings.server.api.thumbnails import thumbnail_response

router = APIRouter(prefix="/api/listings", tags=["listings"])

support_router = APIRouter(tags=["listings-support"])


def _ai_runs(request: Request) -> AiRunRegistry:
    runs: AiRunRegistry = request.app.state.ai.registry
    return runs


def _warm_scenes(request: Request, name: str) -> None:
    warmer: SceneWarmer = request.app.state.scene_warmer
    warmer.request(name)


def _etsy_states(request: Request, *, stale_ok: bool = False) -> EtsyStates:
    """Etsy's listing states through the process's short memo (``etsystate.py``)."""
    workspace = app_state.workspace(request)
    client_for = app_state.clients(request).etsy_listing

    def lookup(listing_ids: Sequence[int]) -> Mapping[int, str | None]:
        return etsy_states(workspace.root, listing_ids, client_for=client_for, stale_ok=stale_ok)

    return lookup


def _etsy_states_to_draw(request: Request) -> EtsyStates:
    """For a read that only draws the states, never one that decides on them."""
    return _etsy_states(request, stale_ok=True)


@dataclass(frozen=True)
class Target:
    workspace: Workspace
    name: str


def _require_listing(workspace: Workspace, name: str) -> None:
    if not ListingDocuments(workspace).exists(name):
        raise ListingMissingError(name)


def target(request: Request, name: str) -> Target:
    """404 early; the operations re-check under the listing's lock."""
    workspace = app_state.workspace(request)
    _require_listing(workspace, name)
    return Target(workspace=workspace, name=name)


def _wire_issues(issues: Sequence[ValidationIssue]) -> list[dict[str, str]]:
    return [
        {"severity": i.severity, "tab": i.tab, "where": i.where, "message": i.message}
        for i in issues
    ]


def _representative_name(listing: Listing) -> str | None:
    ref = representative(listing.design)
    return None if ref is None else Path(ref).stem


def _summary(row: ListingRow) -> ListingSummary:
    listing = row.listing
    return ListingSummary(
        name=row.name,
        garment_profile=listing.garment_profile if listing is not None else "",
        design=_representative_name(listing) if listing is not None else None,
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
            **garment_fields(profile),
            "description_composed": view.description_composed,
            "design_content_hash": view.design_content_hash,
        },
        context={"currency": workspace.defaults.etsy.currency},
    )


def _detail(
    request: Request, name: str, *, field_errors: dict[str, str] | None = None
) -> ListingDetail:
    workspace = app_state.workspace(request)
    view = read_listing(workspace, name, etsy_states=_etsy_states(request))
    if field_errors:
        view = dataclasses.replace(view, field_errors=field_errors)
    return _project(workspace, view)


def _describe_draft(workspace: Workspace, document: Mapping[str, Any]) -> ListingDetail:
    return _project(workspace, describe_draft(workspace, document))


@router.get("", response_model=list[ListingSummary])
def list_listings(request: Request, response: Response) -> list[ListingSummary]:
    """Every listing, with its status resolved in **one** Etsy round trip for
    the whole table rather than one per row.

    Answers with a ``Server-Timing`` header saying where the time went, so a
    slow table can be read off the browser's network panel."""
    workspace = app_state.workspace(request)
    timer = PhaseTimer()
    with timer.phase("total"):
        rows = listing_rows(workspace, etsy_states=_etsy_states_to_draw(request), timer=timer)
        summaries = [_summary(row) for row in rows]
    response.headers["Server-Timing"] = server_timing(timer.seconds)
    return summaries


def server_timing(seconds: Mapping[str, float]) -> str:
    return ", ".join(f"{name};dur={value * 1000:.1f}" for name, value in seconds.items())


@router.get("/{name}", response_model=ListingDetail)
def get_listing(target: Annotated[Target, Depends(target)], request: Request) -> ListingDetail:
    return _detail(request, target.name)


@router.patch("/{name}", response_model=ListingDetail)
def patch_listing(
    target: Annotated[Target, Depends(target)],
    body: dict[str, Any],
    request: Request,
    background: BackgroundTasks,
) -> ListingDetail:
    """Merge the editor's slice into ``listing.yaml``. A merged document
    that will not validate writes nothing and answers 200 with
    ``field_errors`` beside the listing as it still is. Saved positions
    queue any Marigold coverage inference they need after the response, since
    finding the installed worker can take seconds (ADR-0058)."""
    workspace, name = target.workspace, target.name
    refused = edit_listing(workspace, name, body, batches=app_state.batch_store(request))
    if refused is None:
        _warm_scenes(request, name)
        if "template_positions" in body:
            background.add_task(cover_listing_positions, request.app.state.preparations, name)
    return _detail(request, name, field_errors=refused.field_errors if refused else None)


@router.delete("/{name}", response_model=None)
def delete_listing(
    target: Annotated[Target, Depends(target)], request: Request
) -> ListingSummary | Response:
    """Delete from the listings table.

    No remotes: wiped, 204. Remotes: marked ``lifecycle: deleted``, answering
    with the row left pending. Published: 409 -- retire it instead. Confirm
    is the UI's. What goes with the listing either way is
    :func:`~etsy_listings.core.application.listing_identity.delete_listing`'s.
    """
    workspace, name = target.workspace, target.name
    deletion = delete(
        workspace,
        name,
        batches=app_state.batch_store(request),
        ai_runs=_ai_runs(request),
        etsy_states=_etsy_states(request),
    )
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
    workspace = app_state.workspace(request)
    refused = create(workspace, body.name, body.document)
    if refused is not None:
        return _describe_draft(workspace, body.document)
    _warm_scenes(request, body.name)
    return _detail(request, body.name)


@router.post("/{name}/rename", response_model=ListingDetail)
def rename_listing(
    target: Annotated[Target, Depends(target)], body: RenameListingRequest, request: Request
) -> ListingDetail:
    """Move a listing, whole, to a new name -- with everything keyed by it
    (:func:`~etsy_listings.core.application.listing_identity.rename_listing`).
    """
    rename(
        target.workspace,
        target.name,
        body.new_name,
        batches=app_state.batch_store(request),
        ai_runs=_ai_runs(request),
    )
    return _detail(request, body.new_name)


def _preview_response(
    request: Request, target: Target, template: str, colour: str | None, scene_hash: str | None
) -> Response:
    """The preview a plan run already rendered for this scene (ADR-0040, ADR-0041).

    With ``hash`` (the reviewed plan's ``RenderSceneSnapshot.scene_hash``) that
    plan's file is served as it stands; without, the current hash is
    recomputed, which plans the whole listing again.
    """
    if scene_hash is not None:
        path = target.workspace.preview_file(target.name, template, colour, scene_hash)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="no preview rendered yet for this scene")
        return _png(path)
    factory: ContextFactory = request.app.state.context_factory
    found = lookup_preview(factory(target.workspace, None), target.name, template, colour)
    if found.miss == "blocked":
        raise HTTPException(status_code=404, detail="this listing has no render state yet")
    if found.miss == "no_scene":
        where = f"template {template!r}" + (f", colour {colour!r}" if colour is not None else "")
        raise HTTPException(status_code=404, detail=f"no scene for {where}")
    if found.path is None or not found.path.is_file():
        raise HTTPException(status_code=404, detail="no preview rendered yet for this scene")
    return _png(found.path)


def _png(path: Path) -> Response:
    return Response(
        content=path.read_bytes(), media_type="image/png", headers={"Cache-Control": "no-cache"}
    )


@router.get("/{name}/previews/{template}")
def listing_preview(
    target: Annotated[Target, Depends(target)],
    template: str,
    request: Request,
    content_hash: Annotated[str | None, Query(alias="hash")] = None,
) -> Response:
    """A ``multiple``/``single``-kind scene: no per-colour photo, so no
    colour segment (ADR-0014's rule, mirrored from ``render_file``)."""
    return _preview_response(request, target, template, None, content_hash)


@router.get("/{name}/previews/{template}/{colour}")
def listing_preview_coloured(
    target: Annotated[Target, Depends(target)],
    template: str,
    colour: str,
    request: Request,
    content_hash: Annotated[str | None, Query(alias="hash")] = None,
) -> Response:
    """A ``colour-matrix``-kind scene: one preview per colour."""
    return _preview_response(request, target, template, colour, content_hash)


@router.get("/{name}/scene-preview")
def scene_preview(
    target: Annotated[Target, Depends(target)],
    template: str,
    request: Request,
    query: Annotated[ScenePreviewQuery, Depends()],
) -> Response:
    """One of this listing's scenes, each layer printing the file its depicted
    colour resolves to in the *saved* listing -- the Variants stage and
    every Listing Images picture, multi-colour scenes included (spec:
    *Previews*). Resolved here rather than from a design name in the URL, so
    the editor shows the file Printify prints.

    A layer that resolves to nothing is left bare rather than failing the
    picture (:func:`~etsy_listings.core.application.listing_reads.scene_artwork`).
    Each layer prints at the listing's *saved* position where it holds one
    (ADR-0058), so a landed position save is the composite the render writes.
    ``v`` is ignored; the editor sends a signature of the saved design so a
    landed save is a new URL and the browser fetches it again.

    A full-size scene may be found under pixel digests remembered from before
    a restart, which saves seconds of decoding; the editor then asks
    :func:`check_scene_preview` whether that was the right one.
    """
    layers = _scene_layers(target, template, query.colour)
    if query.scale == "full":
        picture = remembered_scene(target.workspace, template, layers, images=PREVIEW_IMAGES)
    else:
        picture = saved_scene(
            target.workspace, template, layers, size=query.scale, images=PREVIEW_IMAGES
        )
    return scene_response(picture, if_none_match=request.headers.get("if-none-match"))


@router.get("/{name}/scene-preview/check", response_model=SceneCheckResponse)
def check_scene_preview(
    target: Annotated[Target, Depends(target)],
    template: str,
    query: Annotated[ScenePreviewQuery, Depends()],
) -> SceneCheckResponse:
    """Whether :func:`scene_preview` showed a scene found under a remembered
    digest that no longer names its file's pixels, so the editor should
    fetch the picture again. Computes the digests, which corrects them."""
    layers = _scene_layers(target, template, query.colour)
    changed = remembered_scene_was_wrong(target.workspace, template, layers, images=PREVIEW_IMAGES)
    return SceneCheckResponse(changed=changed)


def _scene_layers(target: Target, template: str, colour: str | None) -> SceneLayers:
    """What ``template``'s scene paints for the *saved* listing (A35)."""
    try:
        listing = listing_scenes(target.workspace, target.name)
    except ConfigLoadError as exc:
        raise HTTPException(
            status_code=404, detail=f"listing {target.name!r} does not load"
        ) from exc
    return SceneLayers(colour, listing.artwork, listing.boxes(template))


@router.get("/{name}/scene-artwork")
def scene_artwork_picture(
    target: Annotated[Target, Depends(target)],
    template: str,
    colour: str | None = None,
    placement: str | None = None,
) -> Response:
    """The file one layer of this listing's scene prints, as the editor's live
    Position mode draws it: downscaled and with its transparency, unlike a list
    thumbnail. Resolved here for the reason :func:`scene_preview` is, so the
    picture under a drag and the render that replaces it print the same file.
    ``404`` for a layer left bare."""
    workspace = target.workspace
    try:
        listing = listing_scenes(workspace, target.name)
    except ConfigLoadError as exc:
        raise HTTPException(
            status_code=404, detail=f"listing {target.name!r} does not load"
        ) from exc
    path = layer_artwork(workspace, template, SceneLayers(colour, listing.artwork), placement)
    if path is None:
        raise HTTPException(status_code=404, detail="this layer prints nothing")
    artwork = PREVIEW_IMAGES.design(path, max_edge=LIVE_ARTWORK_EDGE)
    return scene_response(SceneFrame(Image.fromarray(artwork)))


@support_router.get("/api/listing-draft", response_model=ListingDetail)
def listing_draft(request: Request) -> ListingDetail:
    """The listing `+ New listing` opens the editor on, before it has a name.

    The server hands over `EMPTY_DRAFT`: nothing chosen, nothing invented, and
    a block issue for each thing still to pick. ``name`` comes back empty,
    which the editor refuses to save.
    """
    return _describe_draft(app_state.workspace(request), EMPTY_DRAFT)


@support_router.post("/api/listing-draft", response_model=ListingDetail)
def describe_listing_draft(request: Request, body: DraftListingRequest) -> ListingDetail:
    """The same, for a candidate the editor has since edited, so its issues
    stay current before the listing has a name. Writes nothing.
    """
    return _describe_draft(app_state.workspace(request), body.document)


@support_router.get("/api/garment-profiles", response_model=list[GarmentProfileSummary])
def list_garment_profiles(request: Request) -> list[GarmentProfileSummary]:
    facts = WorkspaceFacts.gather(app_state.workspace(request))
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
    workspace = app_state.workspace(request)
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
    workspace = app_state.workspace(request)
    shop_id = workspace.defaults.etsy.shop_id
    if shop_id is None:
        return EtsySectionsResponse(available=False, sections=[])
    client = app_state.clients(request).etsy_shop(workspace.root)
    try:
        sections = client.shop_sections(shop_id)
    except (EtsyApiError, EtsyAuthError, EtsyRefreshBusyError, MissingCredentialError):
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
    workspace = app_state.workspace(request)
    shop_id = workspace.defaults.etsy.shop_id
    if shop_id is None:
        raise HTTPException(
            status_code=409, detail="Configure an Etsy shop before adding a section."
        )
    client = app_state.clients(request).etsy_listing(workspace.root)
    try:
        section = client.create_shop_section(shop_id, body.title)
    except EtsyRefreshBusyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (EtsyAuthError, MissingCredentialError) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except EtsyApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return EtsySectionSummary(id=section.shop_section_id, title=section.title)


@support_router.get("/api/common-copy", response_model=list[CommonCopySummary])
def list_common_copy(request: Request) -> list[CommonCopySummary]:
    """The Description tab's common-copy selector: every reusable description
    body, with the title and summary its front matter carries.

    A file whose front matter will not parse is left out, since picking it
    would fail to resolve. A stored ref that fails to resolve is still a
    details-tab issue.
    """
    workspace = app_state.workspace(request)
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
    workspace = app_state.workspace(request)
    return WorkspaceSummary(
        shop_name=workspace.defaults.etsy.shop_name,
        storage_id=workspace.browser_storage_id(),
    )


@support_router.get("/api/listing-designs", response_model=list[ListingDesignSummary])
def list_listing_designs(request: Request) -> list[ListingDesignSummary]:
    workspace = app_state.workspace(request)
    return [
        ListingDesignSummary(name=path.stem, file=f"designs/{path.name}")
        for path in workspace.design_files()
    ]


@support_router.post("/api/listing-designs", response_model=ListingDesignSummary)
async def upload_listing_design(request: Request, file: UploadFile) -> ListingDesignSummary:
    """A PNG dropped on the editor's design strip, added to ``designs/``.
    The answer names where it landed, which is not always its filename: a
    name already taken by other artwork gets a ``-2`` suffix rather than
    overwriting what another listing may print."""
    payload = await file.read()
    name = save_listing_design(app_state.workspace(request), file.filename or "", payload)
    return ListingDesignSummary(name=name, file=f"designs/{name}.png")


@support_router.get("/api/listing-designs/{name}/thumbnail")
def listing_design_thumbnail(request: Request, name: str) -> Response:
    """The artwork itself, downscaled -- what the listings table, its hover
    card and the editor's design strip all show.

    Served from ``designs/``, never the calibrator's ``test-designs/``.
    """
    workspace = app_state.workspace(request)
    path = workspace.design_file(name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"no design {name!r}")
    return thumbnail_response(path)
