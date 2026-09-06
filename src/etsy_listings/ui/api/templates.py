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

from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
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
from etsy_listings.render.io import encode_png, load_design, load_template_base
from etsy_listings.render.maps import DerivedMapCache
from etsy_listings.render.pipeline import Layer, render_scene
from etsy_listings.ui.api.designs import resolve_design
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


def _colours_from_scene_files(template_dir: Path) -> list[str]:
    if not template_dir.is_dir():
        return []
    return sorted(p.stem for p in template_dir.glob("*.png") if p.stem != "scene")


def _default_box(size: tuple[int, int]) -> BoundingBox:
    w, h = size
    return (
        Point(x=w * 0.2, y=h * 0.2),
        Point(x=w * 0.8, y=h * 0.2),
        Point(x=w * 0.8, y=h * 0.8),
        Point(x=w * 0.2, y=h * 0.8),
    )


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
        )

    if isinstance(config, ColourMatrixTemplate):
        colours = _colours_from_scene_files(workspace.template_dir(name))
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
    )


@router.get("", response_model=list[TemplateSummary])
def list_templates(request: Request) -> list[TemplateSummary]:
    workspace = _workspace(request)
    # include_uncalibrated: the calibrator is what writes template.yaml, so
    # the directories with none are precisely the ones that need this UI.
    names = workspace.template_names(include_uncalibrated=True)
    return [_summarize(workspace, name) for name in names]


def _template_photos(template_dir: Path) -> list[Path]:
    """Every photo in the directory except the scene, sorted."""
    return sorted(p for p in template_dir.glob("*.png") if p.stem != "scene")


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
def colour_report(request: Request, name: str) -> list[ColourReportRow]:
    """What each photo will be taken as if this becomes a colour-matrix set.

    Shown in the kind picker before committing, so a badly named file is seen
    while it is still cheap to think about. A row with ``clean: false`` is one
    ``assign_kind`` will rename on disk (PRD 7a: the filename *is* the
    slugified colour, and a directory whose filenames disagree with the
    colours they mean is the state that rule exists to prevent).
    """
    workspace = _workspace(request)
    template_dir = workspace.template_dir(name)
    if not template_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"no template {name!r}")

    photos = _template_photos(template_dir)
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
def assign_kind(request: Request, name: str, body: AssignKindRequest) -> AnyTemplate:
    """The first calibration step: say what this template is, and get the
    starting ``template.yaml`` for that shape.

    Refuses a template that already has a config. Kind decides the whole file
    shape (A11), so changing it would discard whatever calibration was done in
    the old shape's fields -- and doing that silently, from a picker, is the
    kind of data loss nobody would think to look for.
    """
    workspace = _workspace(request)
    config_path = workspace.template_config_file(name)
    template_dir = workspace.template_dir(name)
    if not template_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"no template {name!r}")
    if config_path.is_file():
        raise HTTPException(
            status_code=409,
            detail=f"{name!r} already has a template.yaml; delete it to change kind",
        )

    photos = _template_photos(template_dir)
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
def thumbnail(request: Request, name: str) -> Response:
    """The template's own photo, downscaled, for the rail.

    Not a render: the rail shows every template in the workspace at once, and
    running the real pipeline once per row would make opening the calibrator
    cost as much as calibrating. Which photo hardly matters -- a colour-matrix
    set's colours are all the same garment -- so this takes ``scene.png`` when
    there is one and the first colour otherwise, without reading the config.

    Regenerated per request rather than cached on disk; the resize is cheap
    next to the response, and a cache in the workspace would be one more
    derived directory to invalidate. Repeat loads are handled by the
    ``Cache-Control`` header instead.
    """
    workspace = _workspace(request)
    template_dir = workspace.template_dir(name)
    if not template_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"no template {name!r}")

    scene = workspace.template_scene_image(name)
    source = scene if scene.is_file() else next(iter(sorted(template_dir.glob("*.png"))), None)
    if source is None:
        raise HTTPException(status_code=404, detail=f"no photo for {name!r}")

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
def get_config(request: Request, name: str) -> AnyTemplate:
    return _load_config(_workspace(request), name)


@router.put("/{name}/config", response_model=TemplateConfig)
def put_config(request: Request, name: str, body: AnyTemplate) -> AnyTemplate:
    workspace = _workspace(request)
    if not workspace.template_config_file(name).parent.is_dir():
        raise HTTPException(status_code=404, detail=f"no template {name!r}")
    workspace.save_template_config(name, body)
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


@router.post("/{name}/preview")
def preview(request: Request, name: str, body: PreviewRequest) -> Response:
    workspace = _workspace(request)
    kind = _load_config(workspace, name).kind
    if not isinstance(body, PREVIEW_BODIES[kind]):
        raise HTTPException(status_code=400, detail=f"expected a {kind} preview body")

    colour = body.colour if isinstance(body, ColourMatrixPreviewRequest) else None
    photo = workspace.scene_photo(name, colour)
    if not photo.path.is_file():
        missing = f"colour {colour!r}" if colour is not None else f"{name!r}"
        raise HTTPException(status_code=404, detail=f"no mockup photo for {missing}")

    base = load_template_base(photo.path)
    design = load_design(resolve_design(workspace, body.design))
    configs = _preview_configs(body)
    cache = DerivedMapCache(workspace.template_derived_dir(name))
    image = render_scene(
        base,
        [Layer(design=design, cfg=cfg) for cfg in configs],
        height=(
            cache.height(photo.map_key, base)
            if any(cfg.displace.enabled for cfg in configs)
            else None
        ),
        luminance=(
            cache.luminance(photo.map_key, base)
            if any(cfg.shade.enabled for cfg in configs)
            else None
        ),
    )
    return Response(content=encode_png(image), media_type="image/png")
