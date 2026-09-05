"""Template authoring endpoints: upload, config, and a live preview through
the *real* renderer (PRD: "the Python backend re-runs the real renderer on
each change and streams back the composite, so the preview is the actual
output, not an approximation").

A template is exactly one of three kinds; the upload widget, the config
shape and the preview request shape all follow which kind is in play.

Every path here comes from ``Workspace``. That is deliberate: template names
arrive from URLs, and routing them through the workspace's accessors means the
"stays inside the root" rule (A8) is enforced by the same code the rest of the
tool uses, instead of a second, bespoke check living in the web layer.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import Response
from PIL import Image

from etsy_listings.config.errors import ConfigLoadError
from etsy_listings.config.slug import slugify
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
from etsy_listings.render.pipeline import Layer, render, render_scene
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
    UploadResponse,
)
from etsy_listings.workspace.workspace import InvalidNameError, Workspace

router = APIRouter(prefix="/api/templates", tags=["templates"])

THUMBNAIL_MAX = 160
"""Longest edge of a rail thumbnail, in px. The rail draws them at ~26x30 CSS
px (wireframe 2a), so this leaves headroom for a HiDPI screen without turning
the list into a megabyte of PNG."""


def _workspace(request: Request) -> Workspace:
    workspace: Workspace = request.app.state.workspace
    return workspace


def _template_config_path(workspace: Workspace, name: str) -> Path:
    """Resolve a template name from a URL, turning a bad one into a 400."""
    try:
        return workspace.template_config_file(name)
    except InvalidNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    """This template's ``template.yaml``, or the right HTTP error.

    Both failures a URL can cause are mapped here rather than at each call
    site: a name that is not a single path segment is the client's fault
    (400), and a template with no config yet is simply absent (404).
    """
    try:
        return workspace.load_template_config(name)
    except InvalidNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConfigLoadError as exc:
        raise HTTPException(status_code=404, detail=f"no template.yaml for {name!r}") from exc


def _status_reason(config: AnyTemplate) -> str | None:
    """Why this template is not ready to render from, or ``None`` if it is.

    Only ``multiple`` has states beyond "has a config at all": a chart is
    written with an empty ``placements`` list at upload, and a box can be
    dragged into place before anyone says which colour it depicts. The other
    two kinds get a bounding box at upload and are usable immediately -- a
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


@router.post("", response_model=UploadResponse)
async def upload_template(
    request: Request, name: str, files: list[UploadFile], kind: TemplateKind | None = None
) -> UploadResponse:
    workspace = _workspace(request)
    config_path = _template_config_path(workspace, name)
    if not files:
        raise HTTPException(status_code=400, detail="upload at least one file")
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if kind is None:
        # Photos in, question later. They keep their own filenames until a
        # kind is assigned, because which name is *correct* depends entirely
        # on the answer: a colour-matrix set's filenames are its colours
        # (PRD 7a), while a scene kind wants the fixed scene.png (PRD 28).
        for upload in files:
            if not upload.filename:
                raise HTTPException(status_code=400, detail="every uploaded file needs a filename")
            try:
                destination = workspace.template_base_image(name, Path(upload.filename).stem)
            except InvalidNameError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            destination.write_bytes(await upload.read())
        return UploadResponse(name=name, kind=None, colours=[])

    if kind == "colour-matrix":
        colours: list[str] = []
        for upload in files:
            if not upload.filename:
                raise HTTPException(status_code=400, detail="every uploaded file needs a filename")
            colour = Path(upload.filename).stem
            try:
                destination = workspace.template_base_image(name, colour)
            except InvalidNameError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            destination.write_bytes(await upload.read())
            colours.append(colour)

        # A freshly uploaded set gets a starting box so the calibrator has
        # something to drag; an existing template.yaml is never overwritten.
        if not config_path.is_file():
            with Image.open(workspace.template_base_image(name, colours[0])) as img:
                size = img.size
            workspace.save_template_config(
                name, ColourMatrixTemplate(bounding_box=_default_box(size))
            )
        return UploadResponse(name=name, kind="colour-matrix", colours=sorted(colours))

    if len(files) != 1:
        raise HTTPException(
            status_code=400, detail=f"{kind} kind expects exactly one photo, got {len(files)}"
        )
    destination = workspace.template_scene_image(name)
    destination.write_bytes(await files[0].read())

    if not config_path.is_file():
        with Image.open(destination) as img:
            size = img.size
        if kind == "multiple":
            workspace.save_template_config(name, MultipleTemplate(placements=[]))
        else:
            workspace.save_template_config(name, SingleTemplate(bounding_box=_default_box(size)))
    return UploadResponse(name=name, kind=kind, colours=[])


def _template_photos(template_dir: Path) -> list[Path]:
    """Every photo in the directory except the scene, sorted."""
    return sorted(p for p in template_dir.glob("*.png") if p.stem != "scene")


@router.get("/{name}/colour-report", response_model=list[ColourReportRow])
def colour_report(request: Request, name: str) -> list[ColourReportRow]:
    """What each photo would be taken as if this became a colour-matrix set.

    Shown in the kind picker before committing, so a badly named file is
    caught while it is still cheap to rename. Reporting only -- PRD 7a makes
    the filename the source of truth and there is deliberately no mapping
    table to edit here.
    """
    workspace = _workspace(request)
    try:
        template_dir = workspace.template_dir(name)
    except InvalidNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not template_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"no template {name!r}")

    return [
        ColourReportRow(
            filename=photo.name, colour=slugify(photo.stem), clean=slugify(photo.stem) == photo.stem
        )
        for photo in _template_photos(template_dir)
    ]


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
    config_path = _template_config_path(workspace, name)
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
        raise HTTPException(status_code=400, detail=f"no photos uploaded for {name!r}")

    if body.kind == "colour-matrix":
        # Nothing is renamed: these filenames already are the colours.
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
    try:
        template_dir = workspace.template_dir(name)
    except InvalidNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    if not _template_config_path(workspace, name).parent.is_dir():
        raise HTTPException(status_code=404, detail=f"no template {name!r}")
    workspace.save_template_config(name, body)
    return body


@router.post("/{name}/preview")
def preview(request: Request, name: str, body: PreviewRequest) -> Response:
    workspace = _workspace(request)
    template_cfg = _load_config(workspace, name)
    design = load_design(resolve_design(workspace, body.design))
    cache = DerivedMapCache(workspace.template_derived_dir(name))

    if isinstance(template_cfg, ColourMatrixTemplate):
        if not isinstance(body, ColourMatrixPreviewRequest):
            raise HTTPException(status_code=400, detail="expected a colour-matrix preview body")
        try:
            base_path = workspace.template_base_image(name, body.colour)
        except InvalidNameError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not base_path.is_file():
            raise HTTPException(status_code=404, detail=f"no base image for colour {body.colour!r}")
        base = load_template_base(base_path)
        cfg = RenderConfig(bounding_box=body.bounding_box, displace=body.displace, shade=body.shade)
        image = render(
            design,
            base,
            cfg,
            height=cache.height(body.colour, base) if cfg.displace.enabled else None,
            luminance=cache.luminance(body.colour, base) if cfg.shade.enabled else None,
        )
        return Response(content=encode_png(image), media_type="image/png")

    if isinstance(template_cfg, SingleTemplate):
        if not isinstance(body, SinglePreviewRequest):
            raise HTTPException(status_code=400, detail="expected a single preview body")
        base_path = workspace.template_scene_image(name)
        if not base_path.is_file():
            raise HTTPException(status_code=404, detail=f"no scene image for {name!r}")
        base = load_template_base(base_path)
        cfg = RenderConfig(bounding_box=body.bounding_box, displace=body.displace, shade=body.shade)
        image = render(
            design,
            base,
            cfg,
            height=cache.height(name, base) if cfg.displace.enabled else None,
            luminance=cache.luminance(name, base) if cfg.shade.enabled else None,
        )
        return Response(content=encode_png(image), media_type="image/png")

    if not isinstance(body, MultiplePreviewRequest):
        raise HTTPException(status_code=400, detail="expected a multiple preview body")
    base_path = workspace.template_scene_image(name)
    if not base_path.is_file():
        raise HTTPException(status_code=404, detail=f"no scene image for {name!r}")
    base = load_template_base(base_path)
    layers = [
        Layer(
            design=design,
            cfg=RenderConfig(bounding_box=p.bounding_box, displace=body.displace, shade=body.shade),
        )
        for p in body.placements
    ]
    image = render_scene(
        base,
        layers,
        height=cache.height(name, base) if body.displace.enabled else None,
        luminance=cache.luminance(name, base) if body.shade.enabled else None,
    )
    return Response(content=encode_png(image), media_type="image/png")
