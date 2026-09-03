"""Template authoring endpoints: upload, quad/displace/shade config, and a live
preview through the *real* renderer (PRD: "the Python backend re-runs the real
renderer on each change and streams back the composite, so the preview is the
actual output, not an approximation").

Every path here comes from ``Workspace``. That is deliberate: template names
arrive from URLs, and routing them through the workspace's accessors means the
"stays inside the root" rule (A8) is enforced by the same code the rest of the
tool uses, instead of a second, bespoke check living in the web layer.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import Response
from PIL import Image

from etsy_listings.render.config import RenderConfig, TemplateConfig, WarpConfig
from etsy_listings.render.io import encode_png, load_design, load_template_base
from etsy_listings.render.maps import DerivedMapCache
from etsy_listings.render.pipeline import render
from etsy_listings.ui.api.schemas import (
    PreviewRequest,
    TemplateConfigResponse,
    TemplateConfigUpdate,
    TemplateSummary,
    UploadResponse,
)
from etsy_listings.workspace.workspace import InvalidNameError, Workspace

router = APIRouter(prefix="/api/templates", tags=["templates"])

BUNDLED_DESIGN = Path(__file__).parent / "static" / "bundled-test-design.png"


def _workspace(request: Request) -> Workspace:
    workspace: Workspace = request.app.state.workspace
    return workspace


def _template_config_path(workspace: Workspace, name: str) -> Path:
    """Resolve a template name from a URL, turning a bad one into a 400."""
    try:
        return workspace.template_config_file(name)
    except InvalidNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _colours(template_dir: Path) -> list[str]:
    if not template_dir.is_dir():
        return []
    return sorted(p.stem for p in template_dir.glob("*.png"))


def _default_quad(size: tuple[int, int]) -> WarpConfig:
    w, h = size
    return WarpConfig(
        quad=(
            (w * 0.2, h * 0.2),
            (w * 0.8, h * 0.2),
            (w * 0.8, h * 0.8),
            (w * 0.2, h * 0.8),
        )
    )


def _read_template_config(path: Path) -> TemplateConfig:
    return TemplateConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _write_template_config(path: Path, config: TemplateConfig) -> None:
    path.write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )


def _as_response(config: TemplateConfig) -> TemplateConfigResponse:
    return TemplateConfigResponse(warp=config.warp, displace=config.displace, shade=config.shade)


@router.get("", response_model=list[TemplateSummary])
def list_templates(request: Request) -> list[TemplateSummary]:
    workspace = _workspace(request)
    templates_root = workspace.templates_dir()
    if not templates_root.is_dir():
        return []
    return [
        TemplateSummary(
            name=entry.name,
            colours=_colours(entry),
            has_config=workspace.template_config_file(entry.name).is_file(),
        )
        for entry in sorted(templates_root.iterdir())
        if entry.is_dir()
    ]


@router.post("", response_model=UploadResponse)
async def upload_template(request: Request, name: str, files: list[UploadFile]) -> UploadResponse:
    workspace = _workspace(request)
    config_path = _template_config_path(workspace, name)
    if not files:
        raise HTTPException(status_code=400, detail="upload at least one colour image")

    config_path.parent.mkdir(parents=True, exist_ok=True)
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

    # A freshly uploaded set gets a starting quad so the calibrator has
    # something to drag; an existing template.yaml is never overwritten.
    if not config_path.is_file():
        with Image.open(workspace.template_base_image(name, colours[0])) as img:
            size = img.size
        _write_template_config(config_path, TemplateConfig(warp=_default_quad(size)))

    return UploadResponse(name=name, colours=sorted(colours))


@router.get("/{name}/config", response_model=TemplateConfigResponse)
def get_config(request: Request, name: str) -> TemplateConfigResponse:
    config_path = _template_config_path(_workspace(request), name)
    if not config_path.is_file():
        raise HTTPException(status_code=404, detail=f"no template.yaml for {name!r}")
    return _as_response(_read_template_config(config_path))


@router.put("/{name}/config", response_model=TemplateConfigResponse)
def put_config(request: Request, name: str, body: TemplateConfigUpdate) -> TemplateConfigResponse:
    config_path = _template_config_path(_workspace(request), name)
    if not config_path.parent.is_dir():
        raise HTTPException(status_code=404, detail=f"no template {name!r}")

    config = TemplateConfig(warp=body.warp, displace=body.displace, shade=body.shade)
    _write_template_config(config_path, config)
    return _as_response(config)


@router.post("/{name}/preview")
def preview(request: Request, name: str, body: PreviewRequest) -> Response:
    workspace = _workspace(request)
    try:
        base_path = workspace.template_base_image(name, body.colour)
    except InvalidNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not base_path.is_file():
        raise HTTPException(status_code=404, detail=f"no base image for colour {body.colour!r}")

    base = load_template_base(base_path)
    cfg = RenderConfig(warp=body.warp, displace=body.displace, shade=body.shade)
    cache = DerivedMapCache(workspace.template_derived_dir(name))

    image = render(
        load_design(BUNDLED_DESIGN),
        base,
        cfg,
        height=cache.height(body.colour, base) if cfg.displace.enabled else None,
        luminance=cache.luminance(body.colour, base) if cfg.shade.enabled else None,
    )
    return Response(content=encode_png(image), media_type="image/png")
