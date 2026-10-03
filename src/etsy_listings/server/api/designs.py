"""The calibrator's test-design library over HTTP.

Calibration is judged by eye. The bundled grid target answers "is the warp
right?" precisely and says nothing about how a real ink weight sits on a real
garment, so the set of things you can preview against has to be open: three
bundled targets (static files this package ships) plus whatever the user
uploads. What an upload may be called, whether it is an image and where it
lands are ``core/application/calibration_designs.py``'s; this module decodes
the request and maps its refusals to 400.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import Response

from etsy_listings.core.application.calibration_designs import (
    save_uploaded_design,
    uploaded_design,
)
from etsy_listings.core.application.refusals import (
    CalibrationDesignMissing,
    DesignUploadRefused,
)
from etsy_listings.core.workspace.workspace import Workspace
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


def _workspace(request: Request) -> Workspace:
    workspace: Workspace = request.app.state.workspace
    return workspace


def resolve_design(workspace: Workspace, design: str) -> Path:
    """Turn an id from the library into a file on disk.

    A stale id is a 400 rather than a ``KeyError`` escaping as a 500: the
    client picked it from a list this API handed out, so an id that no longer
    exists means the list moved on, not that the server broke.
    """
    bundled = BUNDLED_DESIGNS.get(design)
    if bundled is not None:
        return bundled
    try:
        return uploaded_design(workspace, design)
    except CalibrationDesignMissing as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[DesignSummary])
def list_designs(request: Request) -> list[DesignSummary]:
    workspace = _workspace(request)
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
    return thumbnail_response(resolve_design(_workspace(request), design))


@router.post("", response_model=DesignSummary)
async def upload_design(request: Request, file: UploadFile) -> DesignSummary:
    payload = await file.read()
    try:
        design = save_uploaded_design(_workspace(request), file.filename or "", payload)
    except DesignUploadRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DesignSummary(id=design, label=design, source="upload")
