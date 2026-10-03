"""The calibrator's uploaded test designs, called directly.

What ``POST /api/designs`` used to decide inside the route: which filenames
an upload may use, that its bytes are an image before anything is written,
and where it lands. The route's status codes and multipart decoding stay in
``tests/server/behaviour/test_calibrator_api.py``.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from etsy_listings.core.application.calibration_designs import (
    save_uploaded_design,
    uploaded_design,
)
from etsy_listings.core.application.refusals import (
    CalibrationDesignMissing,
    DesignUploadRefused,
)
from etsy_listings.core.workspace.workspace import Workspace


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


def _png() -> bytes:
    buffer = BytesIO()
    Image.new("RGBA", (64, 64), (200, 60, 60, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_an_upload_lands_in_the_workspace_library_under_its_stem(workspace: Workspace) -> None:
    design = save_uploaded_design(workspace, "my-artwork.png", _png())

    assert design == "my-artwork"
    assert workspace.test_design_file("my-artwork").read_bytes() == _png()
    assert uploaded_design(workspace, design) == workspace.test_design_file("my-artwork")


@pytest.mark.parametrize("filename", ["", "../../evil.png", "nested/evil.png"])
def test_a_name_that_is_not_a_plain_filename_is_refused_and_nothing_written(
    workspace: Workspace, filename: str
) -> None:
    with pytest.raises(DesignUploadRefused):
        save_uploaded_design(workspace, filename, _png())

    assert workspace.test_design_names() == []


def test_bytes_that_are_not_an_image_are_refused_before_anything_is_written(
    workspace: Workspace,
) -> None:
    with pytest.raises(DesignUploadRefused, match="not a readable image"):
        save_uploaded_design(workspace, "notes.png", b"not a png")

    assert workspace.test_design_names() == []


def test_an_unknown_upload_is_refused_by_name(workspace: Workspace) -> None:
    with pytest.raises(CalibrationDesignMissing, match="no-such-design"):
        uploaded_design(workspace, "no-such-design")
