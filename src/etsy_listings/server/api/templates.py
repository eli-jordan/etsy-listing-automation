"""Template authoring endpoints: listing, kind assignment, config, and a live
preview through the real renderer. Each change produces the actual composite,
so the preview shows the same output as deployment.

The calibration rules are
:mod:`etsy_listings.core.application.mockup_templates`' (module-structure
plan, PR 7); this module decides what each answer is on the wire, and keeps
what only serving a browser needs:

* A template, config or photo that is not there is a ``404``; a kind the
  photos cannot be, colliding colour slugs or preview geometry for another
  kind is a ``400``; assigning a kind to a calibrated template is a ``409``.
  An unusable name is the app-wide ``400`` (``InvalidNameError``).
* Previews decode through the process's memo (:mod:`.imagecache`), which a
  drag hits several times a second, and are encoded here: WebP for the
  editor's canvas, deterministic PNG for the full-size Preview tab.
* Thumbnails and photos are HTTP media responses.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass
from email.utils import format_datetime
from functools import cache
from io import BytesIO
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response
from PIL import Image

from etsy_listings.core.application import mockup_templates as calibration
from etsy_listings.core.application.mockup_templates import (
    PreviewGeometry,
    PreviewScene,
    TemplateOverview,
    compose_preview,
    read_config,
    require_template,
    save_calibration,
    template_photo,
    template_swatch,
    unsaved_preview,
)
from etsy_listings.core.application.preparation.previews import EDITOR_ARTWORK_EDGE, editor_preview
from etsy_listings.core.application.prepared_previews import (
    PhotoWarpPreview,
    PreparedPreview,
    photo_warp_preview,
    prepared_preview,
    saved_scene,
)
from etsy_listings.core.application.refusals import (
    TemplateAlreadyCalibrated,
    TemplateConfigMissing,
    TemplateKindRefused,
    TemplateMissing,
    TemplatePhotoMissing,
    TemplatePreviewKindMismatch,
)
from etsy_listings.core.config.slug import SlugCollisionError
from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.preparation.readiness import catalog_readiness
from etsy_listings.core.render import MarigoldRenderer, load_template_config
from etsy_listings.core.render.config import AnyTemplate, PreparationRequired, TemplateConfig
from etsy_listings.core.render.io import encode_png
from etsy_listings.core.workspace.calibration import CalibrationConflict
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.designs import resolve_design
from etsy_listings.server.api.imagecache import (
    EDITOR_MAX_EDGE,
    PREVIEW_IMAGES,
)
from etsy_listings.server.api.schemas import (
    AssignKindRequest,
    CalibrationSaveRequest,
    ColourMatrixPreviewRequest,
    ColourReportRow,
    MapReadinessResponse,
    MultiplePreviewRequest,
    PreviewRequest,
    SwatchResponse,
    TemplatePhoto,
    TemplateSummary,
)
from etsy_listings.server.api.thumbnails import thumbnail_response

router = APIRouter(prefix="/api/templates", tags=["templates"])


def _workspace(request: Request) -> Workspace:
    workspace: Workspace = request.app.state.workspace
    return workspace


@dataclass(frozen=True)
class Target:
    """A template that exists, and the workspace it lives in -- a 404 before
    the handler runs for one that is not there. The operations check again
    for callers that are not this router."""

    workspace: Workspace
    name: str


def target(request: Request, name: str) -> Target:
    workspace = _workspace(request)
    try:
        require_template(workspace, name)
    except TemplateMissing as exc:
        raise _not_found(exc) from exc
    return Target(workspace=workspace, name=name)


Existing = Annotated[Target, Depends(target)]


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
    )


@router.get("", response_model=list[TemplateSummary])
def list_templates(request: Request) -> list[TemplateSummary]:
    workspace = _workspace(request)
    summaries = []
    for overview in calibration.list_templates(workspace):
        summary = _summary(overview)
        if overview.has_config:
            config = workspace.load_template_config(overview.name)
            summary.renderer = config.renderer.type
            # Catalog reads metadata only. The selected status endpoint validates
            # maps; background client reads fill the other rows without blocking entry.
            known = catalog_readiness(config)
            if known is not None:
                summary.maps = MapReadinessResponse(**asdict(known), can_render=known.can_render)
        summaries.append(summary)
    return summaries


@router.get("/{name}/colour-report", response_model=list[ColourReportRow])
def colour_report(template: Existing) -> list[ColourReportRow]:
    """What each photo will be taken as if this becomes a colour-matrix set,
    shown in the kind picker before committing. ``clean: false`` is a file
    assigning the kind will rename (ADR-0004)."""
    try:
        rows = calibration.colour_report(template.workspace, template.name)
    except SlugCollisionError as exc:
        raise _bad_request(exc) from exc
    return [ColourReportRow(filename=r.filename, colour=r.colour, clean=r.clean) for r in rows]


@router.post("/{name}/kind", response_model=TemplateConfig)
def assign_kind(template: Existing, body: AssignKindRequest) -> AnyTemplate:
    """The first calibration step: say what this template is, and get the
    starting ``template.yaml`` for that shape. Refused for a template that
    already has one -- changing kind would discard its calibration."""
    try:
        return calibration.assign_kind(template.workspace, template.name, body.kind)
    except TemplateAlreadyCalibrated as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (TemplateKindRefused, SlugCollisionError) as exc:
        raise _bad_request(exc) from exc


def _photo(template: Target, colour: str | None) -> Path:
    try:
        return template_photo(template.workspace, template.name, colour)
    except TemplatePhotoMissing as exc:
        raise _not_found(exc) from exc


@router.get("/{name}/thumbnail")
def thumbnail(template: Existing, colour: str | None = None) -> Response:
    """The template's own photo, downscaled, for the rail -- not a render,
    which once per row would make opening the calibrator cost as much as
    calibrating. ``colour`` narrows it to one photo of a colour-matrix set,
    for the listings editor's reel. Which photo is
    :func:`~etsy_listings.core.application.mockup_templates.template_photo`'s
    question; how it is downscaled is :mod:`.thumbnails`'."""
    return thumbnail_response(_photo(template, colour))


@router.get("/{name}/photo")
def photo(template: Existing, colour: str | None = None) -> Response:
    """The same photo at its own resolution, for the listing editors' large
    preview stage when no design is picked yet."""
    source = _photo(template, colour)
    return Response(
        content=source.read_bytes(), media_type="image/png", headers={"Cache-Control": "no-cache"}
    )


@router.get("/{name}/config", response_model=TemplateConfig)
def get_config(template: Existing, response: Response) -> AnyTemplate:
    try:
        saved = read_config(template.workspace, template.name)
    except TemplateConfigMissing as exc:
        raise _not_found(exc) from exc
    response.headers["ETag"] = f'"{saved.revision}"'
    response.headers["Last-Modified"] = format_datetime(saved.modified_at, usegmt=True)
    response.headers["Cache-Control"] = "no-store"
    return saved.config


@router.put("/{name}/config", response_model=TemplateConfig)
def put_config(
    template: Existing,
    body: CalibrationSaveRequest,
    response: Response,
    if_match: Annotated[str, Header()],
    request: Request,
) -> AnyTemplate:
    try:
        saved = save_calibration(
            template.workspace,
            template.name,
            body.config,
            expected_revision=if_match.strip('"'),
            request_id=body.request_id,
            mask_edits=body.mask_edits,
        )
    except CalibrationConflict as exc:
        raise HTTPException(
            status_code=409 if "request ID" in str(exc) else 412, detail=str(exc)
        ) from exc
    except TemplateKindRefused as exc:
        raise _bad_request(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except UserFacingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # Incomplete multiple geometry or missing evidence needs explicit Prepare.
    # The committed Save succeeds; read-only readiness explains that refusal.
    with suppress(UserFacingError, ValueError, OSError):
        request.app.state.preparations.reconcile_saved(template.name)
    response.headers["ETag"] = f'"{saved.revision}"'
    return saved.config


def _geometry(body: PreviewRequest) -> PreviewGeometry:
    """The request's unsaved geometry, in the shape it was posted in. Which
    shape a template takes is decided by the kind it already is, not by
    sniffing the body (``unsaved_preview`` refuses another kind's)."""
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


PreviewScale = Literal["editor", "full"]
"""How big a preview to render.

Two named sizes, not a pixel count from the client. ``full`` is the photo's
own resolution -- what ``apply`` will write, and what the Preview tab shows
when you have stopped adjusting and started judging. ``editor`` is the
downscale the canvas drags against, capped at
:data:`~etsy_listings.server.api.imagecache.EDITOR_MAX_EDGE`.

Naming the sizes rather than accepting an ``?max_edge=`` keeps the number the
server's business: each distinct base size grows its own pair of cached
derived maps in the template's ``_renderer/derived/``, so a client free to ask for any
width would quietly fill that directory with one pair per window size.
"""

EDITOR_MEDIA_TYPE = "image/webp"
"""What an editor frame comes back as.

``encode_png``'s determinism (fixed compression level, no metadata chunks)
exists so a render's bytes can be hashed and compared against the last applied
ones. An editor frame is looked at once and thrown away, so it buys nothing
there -- and PNG's entropy coding is the single most expensive step in
producing one. WebP at this quality is visually indistinguishable for judging
placement, and roughly an order of magnitude cheaper to encode and to send.

A ``full`` preview stays PNG: that one *is* meant to be the output you are
approving, so it should not be the only image in the loop that has been
through a lossy codec.
"""

EDITOR_WEBP_QUALITY = 88
EDITOR_WEBP_METHOD = 1
"""Encoder effort, 0 (fastest) to 6. Low on purpose: this runs inside the
frame budget of a drag, and the few percent of file size a higher setting
saves costs more milliseconds than the transfer does over loopback."""


def _encode_preview(image: Image.Image, scale: PreviewScale) -> Response:
    if scale == "full":
        return Response(content=encode_png(image), media_type="image/png")
    buffer = BytesIO()
    image.save(
        buffer,
        format="WEBP",
        quality=EDITOR_WEBP_QUALITY,
        method=EDITOR_WEBP_METHOD,
    )
    return Response(content=buffer.getvalue(), media_type=EDITOR_MEDIA_TYPE)


def render_preview_response(
    scene: PreviewScene | PreparedPreview,
    scale: PreviewScale,
    *,
    workspace: Workspace,
    if_none_match: str | None = None,
) -> Response:
    """Composite a Photo warp scene from the shared memo rather than off disk:
    a drag is a burst of requests for the same photo, design and derived maps,
    and re-reading them is what made the old editor take seconds per frame.

    A full-size scene of either renderer is the PNG the render stage writes,
    from the scene cache when it was composed before. A prepared one also
    carries the identities that let the editor promote it. Its ETag is the
    scene identity, so a browser holding that picture is answered ``304``
    without the body."""
    composed: PreparedPreview | PhotoWarpPreview | None = (
        scene if isinstance(scene, PreparedPreview) else None
    )
    if isinstance(scene, PreviewScene) and scale == "full":
        composed = photo_warp_preview(
            workspace,
            scene,
            base=lambda path: PREVIEW_IMAGES.base(path).image,
            design=PREVIEW_IMAGES.design,
        )
    if composed is not None:
        headers = {
            "ETag": f'"{composed.render_identity}"',
            "X-Render-Identity": composed.render_identity,
            "Cache-Control": "no-cache",
        }
        if isinstance(composed, PreparedPreview):
            headers["X-Map-Generation"] = composed.generation_id
            headers["X-Calibration-Revision"] = composed.config_revision
        if if_none_match == headers["ETag"]:
            return Response(status_code=304, headers=headers)
        return Response(composed.png, media_type="image/png", headers=headers)
    assert isinstance(scene, PreviewScene)  # noqa: S101 - every composed scene returned above
    base = PREVIEW_IMAGES.base(scene.photo.path, EDITOR_MAX_EDGE if scale == "editor" else None)
    image = compose_preview(
        scene,
        base=base.image,
        scale=base.scale,
        design=PREVIEW_IMAGES.design,
        height=lambda: PREVIEW_IMAGES.height(scene.derived_dir, scene.photo.map_key, base),
        luminance=lambda: PREVIEW_IMAGES.luminance(scene.derived_dir, scene.photo.map_key, base),
    )
    return _encode_preview(image, scale)


@router.post("/{name}/preview")
def preview(template: Existing, body: PreviewRequest, scale: PreviewScale = "full") -> Response:
    """The calibrator's preview of the geometry under the cursor, against a
    design from its own test-design library."""
    workspace = template.workspace
    if isinstance(body.renderer, MarigoldRenderer):
        document = body.model_dump(
            mode="json", exclude={"design", "calibration_revision", "mask_edits"}
        )
        if isinstance(body, ColourMatrixPreviewRequest):
            document.pop("colour")
        config = load_template_config(document)
        if scale == "editor":
            try:
                image = editor_preview(
                    workspace,
                    template.name,
                    config=config,
                    revision=body.calibration_revision or "",
                    mask_edits=body.mask_edits,
                    colour=body.colour if isinstance(body, ColourMatrixPreviewRequest) else None,
                    base=lambda path: PREVIEW_IMAGES.base(path).image,
                    artwork=lambda: PREVIEW_IMAGES.material_design(
                        resolve_design(workspace, body.design), max_edge=EDITOR_ARTWORK_EDGE
                    ),
                )
            except (PreparationRequired, ValueError, OSError) as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            response = _encode_preview(image, "editor")
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Preview-Quality"] = "interactive"
            return response
        if body.mask_edits:
            raise HTTPException(status_code=409, detail="Save draft mask edits before full preview")
        with preview_refusals():
            prepared = prepared_preview(
                workspace,
                template.name,
                config=config,
                colour=body.colour if isinstance(body, ColourMatrixPreviewRequest) else None,
                design=lambda _colour: resolve_design(workspace, body.design),
            )
        return render_preview_response(prepared, scale, workspace=workspace)
    try:
        scene = unsaved_preview(
            workspace,
            template.name,
            _geometry(body),
            design=lambda: resolve_design(workspace, body.design),
        )
    except (TemplateConfigMissing, TemplatePhotoMissing) as exc:
        raise _not_found(exc) from exc
    except PreparationRequired as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except TemplatePreviewKindMismatch as exc:
        raise _bad_request(exc) from exc
    return render_preview_response(scene, scale, workspace=workspace)


@router.get("/{name}/design-preview")
def design_preview(
    template: Existing,
    request: Request,
    design: str | None = None,
    test_design: str | None = None,
    colour: str | None = None,
    scale: PreviewScale = "full",
) -> Response:
    """One design on every layer of this template's saved geometry -- the
    listing-template editor's preview (UI doc §3): a listing template has no
    artwork, so it is viewed through a design picked only to preview with.

    ``design`` is a name from ``GET /api/listing-designs``, resolved through
    ``Workspace.design_file``; ``test_design`` is the calibrator library's id
    instead, through :func:`resolve_design`, bundled grid by default. Exactly
    one of the two -- they name files in different places, and guessing which
    one a bare name meant is how a test target would end up judged as artwork.

    A *listing's* scenes are not previewed here: ``GET
    /api/listings/{name}/scene-preview`` resolves each layer's file from the
    saved listing (A35), so its editor cannot show one file while Printify
    prints another.
    """
    workspace = template.workspace
    if (design is None) == (test_design is None):
        raise HTTPException(status_code=422, detail="give exactly one of design, test_design")

    def design_path() -> Path:
        if test_design is not None:
            return resolve_design(workspace, test_design)
        assert design is not None  # noqa: S101 - exactly one, checked above
        path = workspace.design_file(design)
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"no design {design!r}")
        return path

    # Every layer shows the one file, resolved (and refused) once.
    one_design = cache(design_path)
    with preview_refusals():
        scene = saved_scene(
            workspace, template.name, colour=colour, design=lambda _colour: one_design()
        )
    return render_preview_response(
        scene, scale, workspace=workspace, if_none_match=request.headers.get("if-none-match")
    )


@router.get("/{name}/swatch", response_model=SwatchResponse)
def swatch(template: Existing, colour: str) -> SwatchResponse:
    """This colour's real garment shade, for a quick-glance dot next to its
    name -- sampled off the colour's own photo, decoded through the preview
    memo. Any kind but colour-matrix 404s, as a photo-less colour does."""
    try:
        hex_colour = template_swatch(
            template.workspace,
            template.name,
            colour,
            photo=lambda path: PREVIEW_IMAGES.base(path).image,
        )
    except (TemplateConfigMissing, TemplatePhotoMissing) as exc:
        raise _not_found(exc) from exc
    return SwatchResponse(hex=hex_colour)


@contextmanager
def preview_refusals() -> Iterator[None]:
    """A saved or prepared preview's refusals, as every preview route reports them."""
    try:
        yield
    except PreparationRequired as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except TemplatePreviewKindMismatch as exc:
        raise _bad_request(exc) from exc
    except (TemplateMissing, TemplateConfigMissing, TemplatePhotoMissing) as exc:
        raise _not_found(exc) from exc
