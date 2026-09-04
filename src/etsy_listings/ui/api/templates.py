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

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import Response
from PIL import Image

from etsy_listings.render.config import (
    BoundingBox,
    ColourMatrixTemplate,
    MultipleTemplate,
    Point,
    RenderConfig,
    SingleTemplate,
    TemplateConfig,
    dump_template_config,
    load_template_config,
)
from etsy_listings.render.io import encode_png, load_design, load_template_base
from etsy_listings.render.maps import DerivedMapCache
from etsy_listings.render.pipeline import Layer, render, render_scene
from etsy_listings.ui.api.schemas import (
    BundledDesign,
    ColourMatrixPreviewRequest,
    MultiplePreviewRequest,
    PreviewRequest,
    SinglePreviewRequest,
    TemplateKind,
    TemplateSummary,
    UploadResponse,
)
from etsy_listings.workspace.workspace import InvalidNameError, Workspace

router = APIRouter(prefix="/api/templates", tags=["templates"])

STATIC_DIR = Path(__file__).parent / "static"
BUNDLED_DESIGNS: dict[BundledDesign, Path] = {
    "bundled-grid": STATIC_DIR / "bundled-test-design.png",
    "bundled-on-light": STATIC_DIR / "bundled-test-design-on-light.png",
    "bundled-on-dark": STATIC_DIR / "bundled-test-design-on-dark.png",
}


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


def _read_template_config(
    path: Path,
) -> ColourMatrixTemplate | MultipleTemplate | SingleTemplate:
    import yaml

    return load_template_config(yaml.safe_load(path.read_text(encoding="utf-8")))


def _write_template_config(
    path: Path, config: ColourMatrixTemplate | MultipleTemplate | SingleTemplate
) -> None:
    import yaml

    path.write_text(yaml.safe_dump(dump_template_config(config), sort_keys=False), encoding="utf-8")


def _summarize(workspace: Workspace, name: str) -> TemplateSummary:
    config_path = workspace.template_config_file(name)
    if not config_path.is_file():
        return TemplateSummary(name=name, kind=None, colours=[], has_config=False)

    config = _read_template_config(config_path)
    if isinstance(config, ColourMatrixTemplate):
        colours = _colours_from_scene_files(workspace.template_dir(name))
    elif isinstance(config, MultipleTemplate):
        colours = [p.colour for p in config.placements]
    else:
        colours = [config.colour] if config.colour is not None else []
    return TemplateSummary(name=name, kind=config.kind, colours=colours, has_config=True)


@router.get("", response_model=list[TemplateSummary])
def list_templates(request: Request) -> list[TemplateSummary]:
    workspace = _workspace(request)
    # include_uncalibrated: the calibrator is what writes template.yaml, so
    # the directories with none are precisely the ones that need this UI.
    names = workspace.template_names(include_uncalibrated=True)
    return [_summarize(workspace, name) for name in names]


@router.post("", response_model=UploadResponse)
async def upload_template(
    request: Request, name: str, kind: TemplateKind, files: list[UploadFile]
) -> UploadResponse:
    workspace = _workspace(request)
    config_path = _template_config_path(workspace, name)
    if not files:
        raise HTTPException(status_code=400, detail="upload at least one file")
    config_path.parent.mkdir(parents=True, exist_ok=True)

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
            _write_template_config(
                config_path, ColourMatrixTemplate(bounding_box=_default_box(size))
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
            _write_template_config(config_path, MultipleTemplate(placements=[]))
        else:
            _write_template_config(config_path, SingleTemplate(bounding_box=_default_box(size)))
    return UploadResponse(name=name, kind=kind, colours=[])


@router.get("/{name}/config", response_model=TemplateConfig)
def get_config(
    request: Request, name: str
) -> ColourMatrixTemplate | MultipleTemplate | SingleTemplate:
    config_path = _template_config_path(_workspace(request), name)
    if not config_path.is_file():
        raise HTTPException(status_code=404, detail=f"no template.yaml for {name!r}")
    return _read_template_config(config_path)


@router.put("/{name}/config", response_model=TemplateConfig)
def put_config(
    request: Request,
    name: str,
    body: ColourMatrixTemplate | MultipleTemplate | SingleTemplate,
) -> ColourMatrixTemplate | MultipleTemplate | SingleTemplate:
    config_path = _template_config_path(_workspace(request), name)
    if not config_path.parent.is_dir():
        raise HTTPException(status_code=404, detail=f"no template {name!r}")
    _write_template_config(config_path, body)
    return body


@router.post("/{name}/preview")
def preview(request: Request, name: str, body: PreviewRequest) -> Response:
    workspace = _workspace(request)
    config_path = _template_config_path(workspace, name)
    if not config_path.is_file():
        raise HTTPException(status_code=404, detail=f"no template.yaml for {name!r}")
    template_cfg = _read_template_config(config_path)
    design = load_design(BUNDLED_DESIGNS[body.design])
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
