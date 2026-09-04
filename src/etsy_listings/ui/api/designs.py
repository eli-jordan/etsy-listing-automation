"""The calibrator's test-design library (A16).

Calibration is judged by eye. The bundled grid target answers "is the warp
right?" precisely and says nothing about how a real ink weight sits on a real
garment, so the set of things you can preview against has to be open: three
bundled targets plus whatever the user uploads.

Uploads land in the *workspace* (``test-designs/``), never in this repo, and
never in ``designs/`` -- that directory holds artwork listings actually ship,
and a calibration target is not a product.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile
from PIL import Image, UnidentifiedImageError

from etsy_listings.ui.api.schemas import DesignSummary
from etsy_listings.workspace.workspace import InvalidNameError, Workspace

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


def uploaded_design_ids(workspace: Workspace) -> list[str]:
    directory = workspace.test_designs_dir()
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.png"))


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
        uploaded = workspace.test_design_file(design)
    except InvalidNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not uploaded.is_file():
        raise HTTPException(status_code=400, detail=f"unknown test design {design!r}")
    return uploaded


@router.get("", response_model=list[DesignSummary])
def list_designs(request: Request) -> list[DesignSummary]:
    workspace = _workspace(request)
    bundled = [
        DesignSummary(id=design_id, label=BUNDLED_LABELS[design_id], source="bundled")
        for design_id in BUNDLED_DESIGNS
    ]
    uploads = [
        DesignSummary(id=name, label=name, source="upload")
        for name in uploaded_design_ids(workspace)
    ]
    return bundled + uploads


@router.post("", response_model=DesignSummary)
async def upload_design(request: Request, file: UploadFile) -> DesignSummary:
    workspace = _workspace(request)
    if not file.filename:
        raise HTTPException(status_code=400, detail="the upload needs a filename")
    # Reject rather than sanitise: `Path("../../evil.png").stem` is a
    # perfectly innocent "evil", so trusting the stem alone would silently
    # accept a traversal attempt instead of reporting it.
    if file.filename != Path(file.filename).name:
        raise HTTPException(status_code=400, detail=f"{file.filename!r} is not a plain filename")

    try:
        destination = workspace.test_design_file(Path(file.filename).stem)
    except InvalidNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    payload = await file.read()
    # Decoded before it is written, so a file that is not an image is refused
    # rather than sitting in the library until a preview fails on it.
    try:
        with Image.open(BytesIO(payload)) as probe:
            probe.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="that file is not a readable image") from exc

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return DesignSummary(id=destination.stem, label=destination.stem, source="upload")
