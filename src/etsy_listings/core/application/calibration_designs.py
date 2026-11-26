"""The calibrator's uploaded test designs, kept in the workspace's
``test-designs/`` (architecture, *The calibrator*)."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from etsy_listings.core.application.refusals import (
    CalibrationDesignMissingError,
    DesignUploadRefusedError,
)
from etsy_listings.core.workspace.workspace import Workspace


def save_uploaded_design(workspace: Workspace, filename: str, payload: bytes) -> str:
    if not filename:
        raise DesignUploadRefusedError("the upload needs a filename")
    # Reject, never sanitise: the stem of "../../evil.png" is a harmless "evil".
    if filename != Path(filename).name:
        raise DesignUploadRefusedError(f"{filename!r} is not a plain filename")

    destination = workspace.test_design_file(Path(filename).stem)

    try:
        with Image.open(BytesIO(payload)) as probe:
            probe.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise DesignUploadRefusedError("that file is not a readable image") from exc

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return destination.stem


def uploaded_design(workspace: Workspace, design: str) -> Path:
    path = workspace.test_design_file(design)
    if not path.is_file():
        raise CalibrationDesignMissingError(design)
    return path
