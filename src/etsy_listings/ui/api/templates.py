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
    TemplateKind,
    TemplateSummary,
)
from etsy_listings.workspace.workspace import Workspace

router = APIRouter(prefix="/api/templates", tags=["templates"])

THUMBNAIL_MAX = 160
"""Longest edge of a rail thumbnail, in px. The rail draws them at ~26x30 CSS
px (wireframe 2a), so this leaves headroom for a HiDPI screen without turning
the list into a megabyte of PNG."""


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


@router.get("/{name}/thumbnail")
def thumbnail(template: Existing) -> Response:
    """The template's own photo, downscaled, for the rail.

    Not a render: the rail shows every template in the workspace at once, and
    running the real pipeline once per row would make opening the calibrator
    cost as much as calibrating. Which photo is shown is
    :meth:`~etsy_listings.workspace.workspace.Workspace.template_preview_photo`'s
    question, not this endpoint's.

    Regenerated per request rather than cached on disk; the resize is cheap
    next to the response, and a cache in the workspace would be one more
    derived directory to invalidate. Repeat loads are handled by the
    ``Cache-Control`` header instead.
    """
    source = template.workspace.template_preview_photo(template.name)
    if source is None:
        raise HTTPException(status_code=404, detail=f"no photo for {template.name!r}")

    buffer = BytesIO()
    with Image.open(source) as img:
        img = img.convert("RGB")
        img.thumbnail((THUMBNAIL_MAX, THUMBNAIL_MAX))
        img.save(buffer, format="PNG")
    return Response(
        content=buffer.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "no-cache"},
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


@router.post("/{name}/preview")
def preview(template: Existing, body: PreviewRequest, scale: PreviewScale = "full") -> Response:
    workspace, name = template.workspace, template.name
    kind = _load_config(workspace, name).kind
    if not isinstance(body, PREVIEW_BODIES[kind]):
        raise HTTPException(status_code=400, detail=f"expected a {kind} preview body")

    colour = body.colour if isinstance(body, ColourMatrixPreviewRequest) else None
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
    design = PREVIEW_IMAGES.design(resolve_design(workspace, body.design))
    configs = [_scaled(cfg, base.scale) for cfg in _preview_configs(body)]
    derived = workspace.template_derived_dir(name)
    image = render_scene(
        base.image,
        [Layer(design=design, cfg=cfg) for cfg in configs],
        height=(
            PREVIEW_IMAGES.height(derived, photo.map_key, base)
            if any(cfg.displace.enabled for cfg in configs)
            else None
        ),
        luminance=(
            PREVIEW_IMAGES.luminance(derived, photo.map_key, base)
            if any(cfg.shade.enabled for cfg in configs)
            else None
        ),
    )
    return _encode_preview(image, scale)
