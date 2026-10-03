"""The calibrator's uploaded test designs.

Calibration is judged by eye, so the set of artwork a preview can use is open:
the server's bundled targets plus whatever the seller uploads. Uploads land in
the *workspace* (``test-designs/``), never in this repo and never in
``designs/`` -- that directory holds artwork listings actually ship, and a
calibration target is not a product.

What an upload may be called and whether it is an image are decided here;
the bundled targets are server static files, and decoding the multipart
request is the route's (module-structure plan, PR 7: uploaded bytes and
filenames may enter core, request objects may not).
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from etsy_listings.core.application.refusals import (
    CalibrationDesignMissing,
    DesignUploadRefused,
)
from etsy_listings.core.workspace.workspace import Workspace


def save_uploaded_design(workspace: Workspace, filename: str, payload: bytes) -> str:
    """Add an upload to the library and answer the id it is offered under
    (its filename stem). Refuses with :class:`DesignUploadRefused`, writing
    nothing, unless ``filename`` is a plain filename and ``payload`` decodes
    as an image."""
    if not filename:
        raise DesignUploadRefused("the upload needs a filename")
    # Reject rather than sanitise: `Path("../../evil.png").stem` is a
    # perfectly innocent "evil", so trusting the stem alone would silently
    # accept a traversal attempt instead of reporting it.
    if filename != Path(filename).name:
        raise DesignUploadRefused(f"{filename!r} is not a plain filename")

    destination = workspace.test_design_file(Path(filename).stem)

    # Decoded before it is written, so a file that is not an image is refused
    # rather than sitting in the library until a preview fails on it.
    try:
        with Image.open(BytesIO(payload)) as probe:
            probe.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise DesignUploadRefused("that file is not a readable image") from exc

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return destination.stem


def uploaded_design(workspace: Workspace, design: str) -> Path:
    """The file behind an uploaded design's id, or
    :class:`CalibrationDesignMissing`."""
    path = workspace.test_design_file(design)
    if not path.is_file():
        raise CalibrationDesignMissing(design)
    return path
