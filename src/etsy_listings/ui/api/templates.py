"""Template authoring endpoints: upload, quad/displace/shade config, and a live
preview through the *real* renderer (PRD: "the Python backend re-runs the real
renderer on each change and streams back the composite, so the preview is the
actual output, not an approximation").
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
from etsy_listings.workspace.workspace import Workspace

router = APIRouter(prefix="/api/templates", tags=["templates"])

BUNDLED_DESIGN = Path(__file__).parent / "static" / "bundled-test-design.png"


def _workspace(request: Request) -> Workspace:
    workspace: Workspace = request.app.state.workspace
    return workspace


def _template_dir(workspace: Workspace, name: str) -> Path:
    template_dir = workspace.root / "mockup-templates" / name
    try:
        template_dir.relative_to(workspace.root)
    except ValueError as exc:  # pragma: no cover - name is a single path segment
        raise HTTPException(status_code=400, detail="invalid template name") from exc
    if "/" in name or "\\" in name or name in ("", ".", ".."):
        raise HTTPException(status_code=400, detail="invalid template name")
    return template_dir


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


@router.get("", response_model=list[TemplateSummary])
def list_templates(request: Request) -> list[TemplateSummary]:
    workspace = _workspace(request)
    templates_root = workspace.root / "mockup-templates"
    if not templates_root.is_dir():
        return []
    summaries = []
    for entry in sorted(templates_root.iterdir()):
        if not entry.is_dir():
            continue
        summaries.append(
            TemplateSummary(
                name=entry.name,
                colours=_colours(entry),
                has_config=(entry / "template.yaml").is_file(),
            )
        )
    return summaries


@router.post("", response_model=UploadResponse)
async def upload_template(request: Request, name: str, files: list[UploadFile]) -> UploadResponse:
    workspace = _workspace(request)
    template_dir = _template_dir(workspace, name)
    if not files:
        raise HTTPException(status_code=400, detail="upload at least one colour image")

    template_dir.mkdir(parents=True, exist_ok=True)
    colours: list[str] = []
    for upload in files:
        if not upload.filename:
            raise HTTPException(status_code=400, detail="every uploaded file needs a filename")
        colour = Path(upload.filename).stem
        contents = await upload.read()
        (template_dir / f"{colour}.png").write_bytes(contents)
        colours.append(colour)

    if not (template_dir / "template.yaml").is_file():
        with Image.open(template_dir / f"{colours[0]}.png") as img:
            size = img.size
        default_config = TemplateConfig(warp=_default_quad(size))
        (template_dir / "template.yaml").write_text(
            yaml.safe_dump(default_config.model_dump(mode="json"), sort_keys=False),
            encoding="utf-8",
        )

    return UploadResponse(name=name, colours=sorted(colours))


@router.get("/{name}/config", response_model=TemplateConfigResponse)
def get_config(request: Request, name: str) -> TemplateConfigResponse:
    workspace = _workspace(request)
    template_dir = _template_dir(workspace, name)
    config_path = template_dir / "template.yaml"
    if not config_path.is_file():
        raise HTTPException(status_code=404, detail=f"no template.yaml for {name!r}")
    config = TemplateConfig.model_validate(yaml.safe_load(config_path.read_text(encoding="utf-8")))
    return TemplateConfigResponse(warp=config.warp, displace=config.displace, shade=config.shade)


@router.put("/{name}/config", response_model=TemplateConfigResponse)
def put_config(request: Request, name: str, body: TemplateConfigUpdate) -> TemplateConfigResponse:
    workspace = _workspace(request)
    template_dir = _template_dir(workspace, name)
    if not template_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"no template {name!r}")

    config = TemplateConfig(warp=body.warp, displace=body.displace, shade=body.shade)
    (template_dir / "template.yaml").write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    return TemplateConfigResponse(warp=config.warp, displace=config.displace, shade=config.shade)


@router.post("/{name}/preview")
def preview(request: Request, name: str, body: PreviewRequest) -> Response:
    workspace = _workspace(request)
    template_dir = _template_dir(workspace, name)
    base_path = template_dir / f"{body.colour}.png"
    if not base_path.is_file():
        raise HTTPException(status_code=404, detail=f"no base image for colour {body.colour!r}")

    design = load_design(BUNDLED_DESIGN)
    base = load_template_base(base_path)
    cache = DerivedMapCache(template_dir / "_derived")

    cfg = RenderConfig(warp=body.warp, displace=body.displace, shade=body.shade)
    height = cache.height(body.colour, base) if cfg.displace.enabled else None
    luminance = cache.luminance(body.colour, base) if cfg.shade.enabled else None

    image = render(design, base, cfg, height=height, luminance=luminance)
    return Response(content=encode_png(image), media_type="image/png")
