"""Template authoring endpoints: listing, kind assignment, config, and a live
preview through the *real* renderer (PRD: "the Python backend re-runs the real
renderer on each change and streams back the composite, so the preview is the
actual output, not an approximation").

Nothing here creates a template. A template is a folder of photos the user
puts in the workspace (PRD, Template authoring), so these endpoints all name
one that already exists.

A template is exactly one of three kinds; the config shape and the preview
request shape both follow which kind is in play.

Every path here comes from ``Workspace``. That is deliberate: template names
arrive from URLs, and routing them through the workspace's accessors means the
"stays inside the root" rule (A8) is enforced by the same code the rest of the
tool uses, instead of a second, bespoke check living in the web layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from PIL import Image

from etsy_listings.config.errors import ConfigLoadError
from etsy_listings.config.slug import SlugCollisionError, slug_map
from etsy_listings.render.config import (
    AnyTemplate,
    BoundingBox,
    ColourMatrixTemplate,
    MultipleTemplate,
    Point,
    RenderConfig,
    SingleTemplate,
    TemplateConfig,
)
from etsy_listings.render.io import encode_png
from etsy_listings.render.pipeline import Layer, render_scene
from etsy_listings.render.swatch import sample_swatch
from etsy_listings.ui.api.designs import resolve_design
from etsy_listings.ui.api.imagecache import (
    EDITOR_MAX_EDGE,
    PREVIEW_IMAGES,
    ScaledBase,
)
from etsy_listings.ui.api.schemas import (
    AssignKindRequest,
    ColourMatrixPreviewRequest,
    ColourReportRow,
    MultiplePreviewRequest,
    PreviewRequest,
    SinglePreviewRequest,
    SwatchResponse,
    TemplateKind,
    TemplatePhoto,
    TemplateSummary,
)
from etsy_listings.ui.api.thumbnails import thumbnail_response
from etsy_listings.workspace import layout
from etsy_listings.workspace.workspace import AmbiguousColourSuffixError, Workspace

router = APIRouter(prefix="/api/templates", tags=["templates"])


def _workspace(request: Request) -> Workspace:
    workspace: Workspace = request.app.state.workspace
    return workspace


@dataclass(frozen=True)
class Target:
    """A template that exists, and the workspace it lives in.

    A dependency rather than a helper, because "does this template exist?" was
    the first line of four endpoints and the answer is a precondition, not a
    step: an endpoint that has one of these cannot be looking at a directory
    that is not there.
    """

    workspace: Workspace
    name: str


def target(request: Request, name: str) -> Target:
    workspace = _workspace(request)
    if not workspace.has_template(name):
        raise HTTPException(status_code=404, detail=f"no template {name!r}")
    return Target(workspace=workspace, name=name)


Existing = Annotated[Target, Depends(target)]


def _default_box(size: tuple[int, int]) -> BoundingBox:
    w, h = size
    return (
        Point(x=w * 0.2, y=h * 0.2),
        Point(x=w * 0.8, y=h * 0.2),
        Point(x=w * 0.8, y=h * 0.8),
        Point(x=w * 0.2, y=h * 0.8),
    )


def _photo_size(workspace: Workspace, name: str) -> tuple[int | None, int | None]:
    """The template's true pixel size, from the image header alone.

    ``Image.open`` is lazy, so this reads a few dozen bytes per template
    rather than decoding one image per row of the rail. An unreadable file
    answers ``None`` rather than raising: a directory with a stray or
    truncated PNG in it should still be listable, since listing it is how the
    user reaches the UI that fixes it.
    """
    photo = workspace.template_preview_photo(name)
    if photo is None:
        return None, None
    try:
        with Image.open(photo) as image:
            width, height = image.size
    except OSError:
        return None, None
    return int(width), int(height)


def _load_config(workspace: Workspace, name: str) -> AnyTemplate:
    """This template's ``template.yaml``, or a 404 if it has none yet.

    An unusable *name* needs nothing here -- ``InvalidNameError`` becomes a
    400 through the app-wide handler in ``app.py``. This only decides that a
    template with no config is absent rather than broken, which is a
    calibrator-specific reading: it is the normal state of a folder of photos
    nobody has given a kind yet.
    """
    try:
        return workspace.load_template_config(name)
    except ConfigLoadError as exc:
        raise HTTPException(status_code=404, detail=f"no template.yaml for {name!r}") from exc


def _status_reason(config: AnyTemplate) -> str | None:
    """Why this template is not ready to render from, or ``None`` if it is.

    Only ``multiple`` has states beyond "has a config at all": a chart is
    written with an empty ``placements`` list when its kind is assigned, and a
    box can be dragged into place before anyone says which colour it depicts.
    The other two kinds get a bounding box then and are usable immediately -- a
    badly positioned box is wrong, but it is not *incomplete*, and the
    calibrator cannot tell the difference.
    """
    if not isinstance(config, MultipleTemplate):
        return None
    if not config.placements:
        return "no boxes"
    uncoloured = sum(1 for p in config.placements if not p.colour.strip())
    if uncoloured:
        noun, verb = ("box", "has") if uncoloured == 1 else ("boxes", "have")
        return f"{uncoloured} {noun} {verb} no colour"
    return None


def _photos(workspace: Workspace, name: str, config: AnyTemplate) -> list[TemplatePhoto]:
    """Where each of this template's scenes really is, workspace-relative.

    Asked of ``Workspace.scene_photo`` rather than composed from PRD 7a's
    convention, because that convention has a documented exception the
    convention itself cannot express -- ``template_base_image``'s
    trailing-segment fallback. An ambiguous colour is skipped rather than
    guessed at, the same answer ``AmbiguousColourSuffixError`` gives everywhere
    else; the client falls back to the plain convention for anything not
    listed here, which is no worse than what it did for all of them before.
    """
    if not isinstance(config, ColourMatrixTemplate):
        scene = workspace.template_scene_image(name)
        return [TemplatePhoto(colour=None, file=_relative(name, scene))]
    photos: list[TemplatePhoto] = []
    for colour in workspace.template_colours(name):
        try:
            path = workspace.scene_photo(name, colour).path
        except AmbiguousColourSuffixError:
            continue
        photos.append(TemplatePhoto(colour=colour, file=_relative(name, path)))
    return photos


def _relative(template: str, photo: Path) -> str:
    """Forward-slashed and workspace-relative, the shape every other served
    path uses (`CommonMediaSummary.file`). Built from the layout rather than
    `relative_to(root)` so it cannot come back as a Windows path."""
    return f"{layout.MOCKUP_TEMPLATES_DIR}/{template}/{photo.name}"


def _summarize(workspace: Workspace, name: str) -> TemplateSummary:
    width, height = _photo_size(workspace, name)
    try:
        config = workspace.load_template_config(name)
    except ConfigLoadError:
        return TemplateSummary(
            name=name,
            kind=None,
            colours=[],
            has_config=False,
            status="needs-calibration",
            status_reason="no kind set",
            width=width,
            height=height,
        )

    if isinstance(config, ColourMatrixTemplate):
        colours = workspace.template_colours(name)
    elif isinstance(config, MultipleTemplate):
        colours = [p.colour for p in config.placements]
    else:
        colours = [config.colour] if config.colour is not None else []
    reason = _status_reason(config)
    return TemplateSummary(
        name=name,
        kind=config.kind,
        colours=colours,
        photos=_photos(workspace, name, config),
        has_config=True,
        status="needs-calibration" if reason else "calibrated",
        status_reason=reason,
        width=width,
        height=height,
    )


@router.get("", response_model=list[TemplateSummary])
def list_templates(request: Request) -> list[TemplateSummary]:
    workspace = _workspace(request)
    # include_uncalibrated: the calibrator is what writes template.yaml, so
    # the directories with none are precisely the ones that need this UI.
    names = workspace.template_names(include_uncalibrated=True)
    return [_summarize(workspace, name) for name in names]


def _colour_slugs(workspace: Workspace, photos: list[Path]) -> dict[Path, str]:
    """Each photo mapped to the colour slug its filename means.

    Goes through ``slug_map`` with the workspace's ``exceptions.yaml``, not a
    bare ``slugify``, so the calibrator computes the *same* slug the rest of
    the tool does -- including the names PRD 7a says will not slugify cleanly
    and are overridden by hand. Two photos landing on one slug is refused
    here rather than silently losing one of them at rename time.
    """
    try:
        slugs = slug_map([photo.stem for photo in photos], workspace.load_exceptions())
    except SlugCollisionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {photo: slugs[photo.stem] for photo in photos}


@router.get("/{name}/colour-report", response_model=list[ColourReportRow])
def colour_report(template: Existing) -> list[ColourReportRow]:
    """What each photo will be taken as if this becomes a colour-matrix set.

    Shown in the kind picker before committing, so a badly named file is seen
    while it is still cheap to think about. A row with ``clean: false`` is one
    ``assign_kind`` will rename on disk (PRD 7a: the filename *is* the
    slugified colour, and a directory whose filenames disagree with the
    colours they mean is the state that rule exists to prevent).
    """
    workspace = template.workspace
    photos = workspace.template_photos(template.name)
    slugs = _colour_slugs(workspace, photos)
    return [
        ColourReportRow(filename=photo.name, colour=slugs[photo], clean=slugs[photo] == photo.stem)
        for photo in photos
    ]


def _rename_photos_to_slugs(workspace: Workspace, photos: list[Path]) -> list[Path]:
    """Rename each photo to ``{slug}.png``, returning the new paths, sorted.

    Case-only renames (``Forest.png`` -> ``forest.png``) go via a temporary
    name: Windows filesystems are case-insensitive, so ``replace()`` straight
    onto a path differing only in case is a no-op there and a rename
    everywhere else -- which would make the calibrator behave differently on
    the two platforms this tool runs on.
    """
    slugs = _colour_slugs(workspace, photos)
    renamed: list[Path] = []
    for photo in photos:
        target = photo.with_name(f"{slugs[photo]}.png")
        # Compared by *name*, not by Path: `WindowsPath("Forest.png") ==
        # WindowsPath("forest.png")` is True, so a Path comparison here skips
        # precisely the case-only rename the staging step below exists for.
        if photo.name == target.name:
            renamed.append(photo)
            continue
        staging = photo.with_name(f".{slugs[photo]}.renaming.png")
        photo.replace(staging)
        staging.replace(target)
        renamed.append(target)
    return sorted(renamed)


@router.post("/{name}/kind", response_model=TemplateConfig)
def assign_kind(template: Existing, body: AssignKindRequest) -> AnyTemplate:
    """The first calibration step: say what this template is, and get the
    starting ``template.yaml`` for that shape.

    Refuses a template that already has a config. Kind decides the whole file
    shape (A11), so changing it would discard whatever calibration was done in
    the old shape's fields -- and doing that silently, from a picker, is the
    kind of data loss nobody would think to look for.
    """
    workspace, name = template.workspace, template.name
    if workspace.template_config_file(name).is_file():
        raise HTTPException(
            status_code=409,
            detail=f"{name!r} already has a template.yaml; delete it to change kind",
        )

    photos = workspace.template_photos(name)
    if not photos:
        raise HTTPException(status_code=400, detail=f"no photos in {name!r}")

    if body.kind == "colour-matrix":
        # Rename each photo to the slug its name means, which is what the
        # colour report just told the user would happen.
        #
        # This used to be a no-op comment claiming "these filenames already
        # are the colours". They are not, for anything a human named:
        # `Heather Grey.png` left the set calibrated and green with a colour
        # called "Heather Grey", while `new` writes the *slug* into a
        # listing's media -- so rendering failed with "no mockup base image
        # for colour 'heather-grey'" against a template the calibrator had
        # just declared finished. PRD 7a makes the filename the slug; this is
        # where that becomes true.
        photos = _rename_photos_to_slugs(workspace, photos)
        with Image.open(photos[0]) as img:
            size = img.size
        config: AnyTemplate = ColourMatrixTemplate(bounding_box=_default_box(size))
    else:
        if len(photos) != 1:
            raise HTTPException(
                status_code=400,
                detail=f"{body.kind} kind expects one photo, found {len(photos)}",
            )
        scene = workspace.template_scene_image(name)
        photos[0].replace(scene)
        with Image.open(scene) as img:
            size = img.size
        config = (
            MultipleTemplate(placements=[])
            if body.kind == "multiple"
            else SingleTemplate(bounding_box=_default_box(size))
        )

    workspace.save_template_config(name, config)
    return config


def _thumbnail_source(template: Existing, colour: str | None) -> Path | None:
    """Which photo :func:`thumbnail` should downscale.

    An ambiguous colour suffix is reported as "no photo" rather than escaping
    as a 500: two candidate files is exactly the case
    ``template_base_image`` refuses to guess at, so there genuinely is no one
    photo to serve, and the caller picked this colour from a list this API
    handed out.
    """
    if colour is None:
        return template.workspace.template_preview_photo(template.name)
    try:
        return template.workspace.template_base_image(template.name, colour)
    except AmbiguousColourSuffixError:
        return None


@router.get("/{name}/thumbnail")
def thumbnail(template: Existing, colour: str | None = None) -> Response:
    """The template's own photo, downscaled, for the rail.

    Not a render: the rail shows every template in the workspace at once, and
    running the real pipeline once per row would make opening the calibrator
    cost as much as calibrating. Which photo is shown is
    :meth:`~etsy_listings.workspace.workspace.Workspace.template_preview_photo`'s
    question, not this endpoint's.

    ``colour`` narrows that to one photo of a ``colour-matrix`` set, for
    callers that are showing a *particular* variant rather than standing in
    for the template: the listings editor's reel draws one tile per
    ``media`` entry, and without this every colour of a set drew the same
    picture, since ``template_preview_photo`` deliberately answers "any one
    of them". Resolution goes through
    :meth:`~etsy_listings.workspace.workspace.Workspace.template_base_image`,
    which owns PRD 7a's filename convention and its trailing-segment
    fallback -- this endpoint must not glob for ``{colour}.png`` itself.

    How it is downscaled and served is :mod:`etsy_listings.ui.api.thumbnails`'
    question -- the listings table asks the same one of a design.
    """
    source = _thumbnail_source(template, colour)
    if source is None or not source.is_file():
        wanted = f"{template.name!r}" if colour is None else f"{template.name!r} colour {colour!r}"
        raise HTTPException(status_code=404, detail=f"no photo for {wanted}")
    return thumbnail_response(source)


@router.get("/{name}/photo")
def photo(template: Existing, colour: str | None = None) -> Response:
    """The template's own photo, at its own resolution -- the bare-scene
    counterpart of ``GET .../design-preview`` for a listing that has not
    picked a design yet.

    Same photo :func:`thumbnail` serves, same resolution rule
    (:func:`_thumbnail_source`), just not downscaled to list size: the
    listing editor's Variants and Listing Images previews are a large hero
    stage, not a row of tiles, and serving them the 160px list thumbnail is
    why that stage used to look tiny for a listing with no design picked yet.
    """
    source = _thumbnail_source(template, colour)
    if source is None or not source.is_file():
        wanted = f"{template.name!r}" if colour is None else f"{template.name!r} colour {colour!r}"
        raise HTTPException(status_code=404, detail=f"no photo for {wanted}")
    return Response(
        content=source.read_bytes(), media_type="image/png", headers={"Cache-Control": "no-cache"}
    )


@router.get("/{name}/config", response_model=TemplateConfig)
def get_config(template: Existing) -> AnyTemplate:
    return _load_config(template.workspace, template.name)


@router.put("/{name}/config", response_model=TemplateConfig)
def put_config(template: Existing, body: AnyTemplate) -> AnyTemplate:
    template.workspace.save_template_config(template.name, body)
    return body


PREVIEW_BODIES: dict[TemplateKind, type[PreviewRequest]] = {
    "colour-matrix": ColourMatrixPreviewRequest,
    "multiple": MultiplePreviewRequest,
    "single": SinglePreviewRequest,
}
"""Which request shape each kind's preview takes. The endpoint validates the
body against the kind the target template already *is*, rather than
shape-sniffing across all three."""


def _preview_configs(body: PreviewRequest) -> list[RenderConfig]:
    """The layers to composite, from the *unsaved* geometry in the request.

    This is the one thing the preview cannot share with the render stage: it
    renders what is currently under the user's cursor, not what
    ``template.yaml`` says. Everything else about the scene -- which photo,
    which derived maps, how they combine -- comes from the same place the
    stage gets it.
    """
    if isinstance(body, MultiplePreviewRequest):
        return [
            RenderConfig(bounding_box=p.bounding_box, displace=body.displace, shade=body.shade)
            for p in body.placements
        ]
    return [RenderConfig(bounding_box=body.bounding_box, displace=body.displace, shade=body.shade)]


PreviewScale = Literal["editor", "full"]
"""How big a preview to render.

Two named sizes, not a pixel count from the client. ``full`` is the photo's
own resolution -- what ``apply`` will write, and what the Preview tab shows
when you have stopped adjusting and started judging. ``editor`` is the
downscale the canvas drags against, capped at
:data:`~etsy_listings.ui.api.imagecache.EDITOR_MAX_EDGE`.

Naming the sizes rather than accepting an ``?max_edge=`` keeps the number the
server's business: each distinct base size grows its own pair of cached
derived maps in the template's ``_derived/``, so a client free to ask for any
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


def _scaled(cfg: RenderConfig, scale: float) -> RenderConfig:
    """``cfg`` restated on a canvas ``scale`` times the photo's true size.

    Bounding boxes arrive in the template's true pixel space -- that is what
    ``template.yaml`` stores and what the editor's overlay works in -- so
    rendering onto a downscaled base means scaling them to match.

    ``displace.strength`` scales with them. It is multiplied by
    ``DISPLACE_MAX_PX``, an absolute pixel figure, so leaving it alone would
    show three times as much fabric distortion in the editor as the render it
    is meant to be predicting -- exactly the wrong direction for a control you
    calibrate by eye.

    ``shade`` is per-pixel and needs no adjustment. ``model_copy`` skips
    revalidation deliberately: the incoming box was already checked for
    degeneracy at its true size, and a valid box must not become a 400 because
    the *preview* happens to be small.
    """
    if scale == 1.0:
        return cfg
    return cfg.model_copy(
        update={
            "bounding_box": tuple(Point(x=p.x * scale, y=p.y * scale) for p in cfg.bounding_box),
            "displace": cfg.displace.model_copy(update={"strength": cfg.displace.strength * scale}),
        }
    )


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


def _render_preview_response(
    workspace: Workspace,
    name: str,
    *,
    colour: str | None,
    configs: list[RenderConfig],
    design_path: Path,
    scale: PreviewScale,
) -> Response:
    """Composite ``design_path`` onto ``name``'s scene photo at ``configs``'
    geometry. Shared by the calibrator's live-drag preview (geometry from the
    request body, design from its own test-design library) and the listing
    editor's read-only preview (geometry from the saved ``template.yaml``,
    design from a listing's real artwork) -- the two differ only in *where*
    those two things come from, never in how the render itself runs.
    """
    photo = workspace.scene_photo(name, colour)
    if not photo.path.is_file():
        missing = f"colour {colour!r}" if colour is not None else f"{name!r}"
        raise HTTPException(status_code=404, detail=f"no mockup photo for {missing}")

    # Everything the render needs comes out of the shared memo rather than off
    # disk: a drag is a burst of requests for the same photo, the same design
    # and the same derived maps, and re-reading them is what made the old
    # editor take seconds per frame.
    base: ScaledBase = PREVIEW_IMAGES.base(
        photo.path, EDITOR_MAX_EDGE if scale == "editor" else None
    )
    design = PREVIEW_IMAGES.design(design_path)
    scaled_configs = [_scaled(cfg, base.scale) for cfg in configs]
    derived = workspace.template_derived_dir(name)
    image = render_scene(
        base.image,
        [Layer(design=design, cfg=cfg) for cfg in scaled_configs],
        height=(
            PREVIEW_IMAGES.height(derived, photo.map_key, base)
            if any(cfg.displace.enabled for cfg in scaled_configs)
            else None
        ),
        luminance=(
            PREVIEW_IMAGES.luminance(derived, photo.map_key, base)
            if any(cfg.shade.enabled for cfg in scaled_configs)
            else None
        ),
    )
    return _encode_preview(image, scale)


@router.post("/{name}/preview")
def preview(template: Existing, body: PreviewRequest, scale: PreviewScale = "full") -> Response:
    workspace, name = template.workspace, template.name
    kind = _load_config(workspace, name).kind
    if not isinstance(body, PREVIEW_BODIES[kind]):
        raise HTTPException(status_code=400, detail=f"expected a {kind} preview body")

    colour = body.colour if isinstance(body, ColourMatrixPreviewRequest) else None
    return _render_preview_response(
        workspace,
        name,
        colour=colour,
        configs=_preview_configs(body),
        design_path=resolve_design(workspace, body.design),
        scale=scale,
    )


def _saved_render_configs(config: AnyTemplate) -> list[RenderConfig]:
    """The layers to composite from *saved* ``template.yaml`` geometry --
    what the listing editor's read-only preview wants, unlike
    :func:`_preview_configs`'s unsaved, still-being-dragged geometry."""
    if isinstance(config, MultipleTemplate):
        return [config.render_config_for(p) for p in config.placements]
    return [config.render_config()]


@router.get("/{name}/design-preview")
def design_preview(
    template: Existing, design: str, colour: str | None = None, scale: PreviewScale = "full"
) -> Response:
    """A listing's *real* artwork, composited onto this template's saved
    geometry -- what the listing editor's Variants/Listing Images tabs show
    so a colour can be judged against the actual design, not a bare photo.

    ``design`` is a name from ``GET /api/listing-designs``, resolved through
    ``Workspace.design_file`` -- deliberately not :func:`resolve_design`,
    which is the calibrator's own test-design library and never sees a
    listing's real artwork.
    """
    workspace, name = template.workspace, template.name
    config = _load_config(workspace, name)
    design_path = workspace.design_file(design)
    if not design_path.is_file():
        raise HTTPException(status_code=404, detail=f"no design {design!r}")

    resolved_colour = colour if isinstance(config, ColourMatrixTemplate) else None
    return _render_preview_response(
        workspace,
        name,
        colour=resolved_colour,
        configs=_saved_render_configs(config),
        design_path=design_path,
        scale=scale,
    )


@router.get("/{name}/swatch", response_model=SwatchResponse)
def swatch(template: Existing, colour: str) -> SwatchResponse:
    """This colour's real garment shade, for a quick-glance dot next to its
    name -- the median pixel (`sample_swatch`) inside the saved bounding box
    of the colour's own scene photo, not an invented hex value. Only a
    ``colour-matrix`` template has one photo per colour to sample; any other
    kind 404s the same way a photo-less colour does.
    """
    workspace, name = template.workspace, template.name
    config = _load_config(workspace, name)
    if not isinstance(config, ColourMatrixTemplate):
        raise HTTPException(status_code=404, detail=f"{name!r} is not a colour-matrix template")

    photo = workspace.scene_photo(name, colour)
    if not photo.path.is_file():
        raise HTTPException(status_code=404, detail=f"no photo for {name!r} colour {colour!r}")

    base = PREVIEW_IMAGES.base(photo.path)
    red, green, blue = sample_swatch(base.image, config.bounding_box)
    return SwatchResponse(hex=f"#{red:02x}{green:02x}{blue:02x}")
