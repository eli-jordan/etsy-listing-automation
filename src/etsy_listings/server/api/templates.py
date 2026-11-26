from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from email.utils import format_datetime
from functools import cache, partial
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response

from etsy_listings.core.application import mockup_templates as calibration
from etsy_listings.core.application.deploy.deployments import Deployments
from etsy_listings.core.application.mockup_templates import (
    CalibrationSave,
    PreviewGeometry,
    TemplateOverview,
    positioned_listings,
    read_config,
    require_template,
    save_calibration,
    template_photo,
    template_swatch,
)
from etsy_listings.core.application.scene_previews import (
    SceneDraft,
    SceneLayers,
    draft_scene,
    saved_scene,
)
from etsy_listings.core.application.template_rename import RenameHosts
from etsy_listings.core.application.template_rename import rename_template as rename
from etsy_listings.core.batches.records import BatchRecords
from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.preparation.readiness import catalog_readiness
from etsy_listings.core.render.config import AnyTemplate, TemplateConfig
from etsy_listings.core.workspace.template_state import (
    TemplateConfigMissingError,
    TemplateConfigUnreadableError,
)
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api import app_state
from etsy_listings.server.api.designs import resolve_design
from etsy_listings.server.api.imagecache import PREVIEW_IMAGES
from etsy_listings.server.api.scene_responses import (
    PreviewQuery,
    PreviewScale,
    scene_response,
)
from etsy_listings.server.api.schemas import (
    AssignKindRequest,
    CalibrationSaveRequest,
    ColourMatrixPreviewRequest,
    ColourReportRow,
    MapReadinessResponse,
    MultiplePreviewRequest,
    PositionedListingResponse,
    PreviewRequest,
    RenameListingRequest,
    SwatchResponse,
    TemplatePhoto,
    TemplateRenameResponse,
    TemplateSummary,
)
from etsy_listings.server.api.thumbnails import thumbnail_response

router = APIRouter(prefix="/api/templates", tags=["templates"])


@dataclass(frozen=True)
class Target:
    workspace: Workspace
    name: str


def target(request: Request, name: str) -> Target:
    workspace = app_state.workspace(request)
    require_template(workspace, name)
    return Target(workspace=workspace, name=name)


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _summary(overview: TemplateOverview) -> TemplateSummary:
    return TemplateSummary(
        name=overview.name,
        kind=overview.kind,
        colours=overview.colours,
        photos=[TemplatePhoto(colour=p.colour, file=p.file) for p in overview.photos],
        has_config=overview.has_config,
        status="calibrated" if overview.calibrated else "needs-calibration",
        status_reason=overview.status_reason,
        width=overview.width,
        height=overview.height,
        labels=overview.labels,
    )


@router.get("", response_model=list[TemplateSummary])
def list_templates(request: Request) -> list[TemplateSummary]:
    summaries = []
    for overview in calibration.list_templates(app_state.workspace(request)):
        summary = _summary(overview)
        if overview.config is not None:
            summary.renderer = overview.config.renderer.type
            # Metadata only: the per-template status endpoint validates the maps.
            known = catalog_readiness(overview.config)
            if known is not None:
                summary.maps = MapReadinessResponse(**asdict(known), can_render=known.can_render)
        summaries.append(summary)
    return summaries


@router.post("/{name}/rename", response_model=TemplateRenameResponse)
def rename_template(
    template: Annotated[Target, Depends(target)], body: RenameListingRequest, request: Request
) -> TemplateRenameResponse:
    """Move a template, and everything naming it, to a new name
    (:mod:`~etsy_listings.core.application.template_rename`). A taken name, a
    running deploy or a preparing template is a ``409``; an unusable name is a
    ``400``."""
    deployments: Deployments = request.app.state.deployments
    done = rename(
        template.workspace,
        template.name,
        body.new_name,
        RenameHosts(
            preparations=request.app.state.preparations,
            records=BatchRecords(app_state.staging_store(request), app_state.batch_store(request)),
            deploying=deployments.busy,
        ),
    )
    return TemplateRenameResponse(
        name=body.new_name, updated=list(done.updated), unresolved=list(done.unresolved)
    )


@router.get("/{name}/colour-report", response_model=list[ColourReportRow])
def colour_report(template: Annotated[Target, Depends(target)]) -> list[ColourReportRow]:
    """What each photo will be taken as if this becomes a colour-matrix set,
    shown in the kind picker before committing. ``clean: false`` is a file
    assigning the kind will rename (ADR-0004)."""
    rows = calibration.colour_report(template.workspace, template.name)
    return [ColourReportRow(filename=r.filename, colour=r.colour, clean=r.clean) for r in rows]


@router.post("/{name}/kind", response_model=TemplateConfig)
def assign_kind(
    template: Annotated[Target, Depends(target)], body: AssignKindRequest
) -> AnyTemplate:
    """The first calibration step: say what this template is, and get the
    starting ``template.yaml`` for that shape. Refused for a template that
    already has one -- changing kind would discard its calibration."""
    return calibration.assign_kind(template.workspace, template.name, body.kind)


def _photo(template: Target, colour: str | None) -> Path:
    return template_photo(template.workspace, template.name, colour)


@router.get("/{name}/thumbnail")
def thumbnail(template: Annotated[Target, Depends(target)], colour: str | None = None) -> Response:
    """The template's own photo, downscaled, for the rail -- not a render, so
    opening the calibrator stays cheap. ``colour`` narrows it to one photo of
    a colour-matrix set, for the listings editor's reel."""
    return thumbnail_response(_photo(template, colour))


@router.get("/{name}/photo")
def photo(template: Annotated[Target, Depends(target)], colour: str | None = None) -> Response:
    """The same photo at its own resolution, for the listing editors' large
    preview stage when no design is picked yet."""
    source = _photo(template, colour)
    return Response(
        content=source.read_bytes(), media_type="image/png", headers={"Cache-Control": "no-cache"}
    )


def _queue_preparation(name: str, after: app_state.AfterResponse) -> None:
    # Incomplete multiple geometry or missing evidence needs explicit Prepare.
    # The committed Save succeeds; read-only readiness explains that refusal.
    with suppress(UserFacingError, ValueError, OSError):
        after.preparations.reconcile_saved(name)
    after.cover_recalibrated(name)


@router.get("/{name}/config", response_model=TemplateConfig)
def get_config(template: Annotated[Target, Depends(target)], response: Response) -> AnyTemplate:
    saved = read_config(template.workspace, template.name)
    response.headers["ETag"] = f'"{saved.revision}"'
    response.headers["Last-Modified"] = format_datetime(saved.modified_at, usegmt=True)
    response.headers["Cache-Control"] = "no-store"
    return saved.config


@router.put("/{name}/config", response_model=TemplateConfig)
def put_config(
    template: Annotated[Target, Depends(target)],
    body: CalibrationSaveRequest,
    response: Response,
    if_match: Annotated[str, Header()],
    after: Annotated[app_state.AfterResponse, Depends(app_state.after_response)],
) -> AnyTemplate:
    try:
        saved = save_calibration(
            template.workspace,
            template.name,
            CalibrationSave(
                config=body.config,
                expected_revision=if_match.strip('"'),
                request_id=body.request_id,
                mask_edits=body.mask_edits,
            ),
        )
    except (TemplateConfigMissingError, TemplateConfigUnreadableError) as exc:
        # The editor shows a 422's sentence. Its 409 means reload, which would
        # not help a saved template.yaml that does not load.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not saved.labels_only:
        _queue_preparation(template.name, after)
    response.headers["ETag"] = f'"{saved.revision}"'
    return saved.config


def _geometry(body: PreviewRequest) -> PreviewGeometry:
    """The request's unsaved geometry, as posted; ``unsaved_preview`` refuses
    a shape other than the template's kind."""
    if isinstance(body, MultiplePreviewRequest):
        return PreviewGeometry(
            kind="multiple",
            boxes=tuple(p.bounding_box for p in body.placements),
            renderer=body.renderer,
        )
    if isinstance(body, ColourMatrixPreviewRequest):
        return PreviewGeometry(
            kind="colour-matrix",
            boxes=(body.bounding_box,),
            colour=body.colour,
            renderer=body.renderer,
        )
    return PreviewGeometry(kind="single", boxes=(body.bounding_box,), renderer=body.renderer)


def _draft(workspace: Workspace, body: PreviewRequest) -> SceneDraft:
    request_only = {"design", "calibration_revision", "mask_edits"}
    if isinstance(body, ColourMatrixPreviewRequest):
        request_only.add("colour")
    return SceneDraft(
        geometry=_geometry(body),
        document=body.model_dump(mode="json", exclude=request_only),
        revision=body.calibration_revision or "",
        mask_edits=body.mask_edits,
        design=lambda: resolve_design(workspace, body.design),
    )


@router.post("/{name}/preview")
def preview(
    template: Annotated[Target, Depends(target)], body: PreviewRequest, scale: PreviewScale = "full"
) -> Response:
    """The calibrator's preview of the geometry under the cursor, against a
    design from its own test-design library."""
    picture = draft_scene(
        template.workspace,
        template.name,
        _draft(template.workspace, body),
        size=scale,
        images=PREVIEW_IMAGES,
    )
    return scene_response(picture)


def _preview_design(
    workspace: Workspace, design: str | None, test_design: str | None
) -> Callable[[], Path]:
    match design, test_design:
        case str() as name, None:
            return partial(_listing_design, workspace, name)
        case None, str() as library_id:
            return partial(resolve_design, workspace, library_id)
    raise HTTPException(status_code=422, detail="give exactly one of design, test_design")


def _listing_design(workspace: Workspace, name: str) -> Path:
    path = workspace.design_file(name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"no design {name!r}")
    return path


@router.get("/{name}/design-preview")
def design_preview(
    template: Annotated[Target, Depends(target)],
    request: Request,
    query: Annotated[PreviewQuery, Depends()],
    design: str | None = None,
    test_design: str | None = None,
) -> Response:
    """One design on every layer of this template's saved geometry -- the
    listing-template editor's preview (UI doc §3): a listing template has no
    artwork, so it is viewed through a design picked only to preview with.

    ``design`` is a name from ``GET /api/listing-designs``, resolved through
    ``Workspace.design_file``; ``test_design`` is the calibrator library's id
    instead, through :func:`resolve_design`, bundled grid by default. Exactly
    one of the two: they name files in different places, and guessing would
    judge a test target as artwork.

    A listing's scenes are previewed by ``GET /api/listings/{name}/scene-preview``.
    """
    workspace, colour, scale = template.workspace, query.colour, query.scale
    design_resolved_once = cache(_preview_design(workspace, design, test_design))
    picture = saved_scene(
        workspace,
        template.name,
        SceneLayers(colour, lambda _colour: design_resolved_once()),
        size=scale,
        images=PREVIEW_IMAGES,
    )
    return scene_response(picture, if_none_match=request.headers.get("if-none-match"))


@router.get("/{name}/positioned-listings", response_model=list[PositionedListingResponse])
def get_positioned_listings(
    template: Annotated[Target, Depends(target)],
) -> list[PositionedListingResponse]:
    """The listings holding positions for this template, which the calibrator
    names around a save (spec, *Recalibration*). Read only."""
    return [
        PositionedListingResponse(listing=held.listing, placements=list(held.placements))
        for held in positioned_listings(template.workspace, template.name)
    ]


@router.get("/{name}/swatch", response_model=SwatchResponse)
def swatch(template: Annotated[Target, Depends(target)], colour: str) -> SwatchResponse:
    """This colour's real garment shade, for a quick-glance dot next to its
    name -- sampled off the colour's own photo, decoded through the preview
    memo. Any kind but colour-matrix 404s, as a photo-less colour does."""
    hex_colour = template_swatch(
        template.workspace,
        template.name,
        colour,
        photo=lambda path: PREVIEW_IMAGES.base(path).image,
    )
    return SwatchResponse(hex=hex_colour)
