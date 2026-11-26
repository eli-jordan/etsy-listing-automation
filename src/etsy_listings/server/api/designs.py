"""The calibrator's test-design library over HTTP.

Three bundled targets plus the user's uploads (docs/architecture.md, *The
calibrator*). ``core/application/calibration_designs.py`` owns names and
validation; the app's refusal table answers what it refuses.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import Response

from etsy_listings.core.application.calibration_designs import (
    save_uploaded_design,
    uploaded_design,
)
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api import app_state
from etsy_listings.server.api.schemas import DesignSummary
from etsy_listings.server.api.thumbnails import thumbnail_response

router = APIRouter(prefix="/api/designs", tags=["designs"])

STATIC_DIR = Path(__file__).parent / "static"

BUNDLED_DESIGNS: dict[str, Path] = {
    "bundled-grid": STATIC_DIR / "bundled-test-design.png",
    "bundled-on-light": STATIC_DIR / "bundled-test-design-on-light.png",
    "bundled-on-dark": STATIC_DIR / "bundled-test-design-on-dark.png",
}

BUNDLED_LABELS: dict[str, str] = {
    "bundled-grid": "Grid / ruler target",
    "bundled-on-light": "Sample art · light ink",
    "bundled-on-dark": "Sample art · dark ink",
}
"""Named for what they show, not for the file behind them -- these are picked
from a menu while looking at a photograph."""


def resolve_design(workspace: Workspace, design: str) -> Path:
    """Turn an id from the library into a file on disk."""
    bundled = BUNDLED_DESIGNS.get(design)
    if bundled is not None:
        return bundled
    return uploaded_design(workspace, design)


@router.get("", response_model=list[DesignSummary])
def list_designs(request: Request) -> list[DesignSummary]:
    workspace = app_state.workspace(request)
    bundled = [
        DesignSummary(id=design_id, label=BUNDLED_LABELS[design_id], source="bundled")
        for design_id in BUNDLED_DESIGNS
    ]
    uploads = [
        DesignSummary(id=name, label=name, source="upload")
        for name in workspace.test_design_names()
    ]
    return bundled + uploads


@router.get("/{design}/thumbnail")
def design_thumbnail(request: Request, design: str) -> Response:
    """A test design, small: what the listing-template editor's
    preview-design row shows beside *Preview design: …* (UI doc §3)."""
    return thumbnail_response(resolve_design(app_state.workspace(request), design))


@router.post("", response_model=DesignSummary)
async def upload_design(request: Request, file: UploadFile) -> DesignSummary:
    payload = await file.read()
    design = save_uploaded_design(app_state.workspace(request), file.filename or "", payload)
    return DesignSummary(id=design, label=design, source="upload")


@router.get("/{design}/image")
def design_image(request: Request, design: str) -> Response:
    """Original RGBA artwork for responsive local placement, without rendering."""
    path = resolve_design(app_state.workspace(request), design)
    return Response(
        path.read_bytes(), media_type="image/png", headers={"Cache-Control": "no-cache"}
    )
