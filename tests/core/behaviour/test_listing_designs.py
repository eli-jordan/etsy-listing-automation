"""Artwork dropped on the editor's design strip, saved into ``designs/``.

Which filenames an upload may use, that its bytes are a PNG before anything
is written, and that it never overwrites artwork another listing may print.
The route's status codes stay in ``tests/server/behaviour/test_listings_api.py``.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from etsy_listings.core.application.listing_designs import save_listing_design
from etsy_listings.core.application.refusals import ListingDesignUploadRefused
from etsy_listings.core.workspace.workspace import Workspace


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


def _image(colour: tuple[int, int, int, int], format: str = "PNG") -> bytes:
    buffer = BytesIO()
    Image.new(
        "RGBA" if format == "PNG" else "RGB", (64, 64), colour[: 4 if format == "PNG" else 3]
    ).save(buffer, format=format)
    return buffer.getvalue()


RED = (200, 60, 60, 255)
BLUE = (60, 60, 200, 255)


def _designs(workspace: Workspace) -> set[str]:
    return {p.name for p in workspace.design_files()}


def test_an_upload_lands_in_designs_under_its_stem(workspace: Workspace) -> None:
    name = save_listing_design(workspace, "sunset-ridge.png", _image(RED))

    assert name == "sunset-ridge"
    assert workspace.design_file("sunset-ridge").read_bytes() == _image(RED)


def test_a_taken_name_with_other_artwork_gets_the_next_free_suffix(workspace: Workspace) -> None:
    save_listing_design(workspace, "sunset-ridge.png", _image(RED))

    assert save_listing_design(workspace, "sunset-ridge.png", _image(BLUE)) == "sunset-ridge-2"
    assert save_listing_design(workspace, "sunset-ridge.png", _image((1, 2, 3, 255))) == (
        "sunset-ridge-3"
    )
    # What was there first is untouched.
    assert workspace.design_file("sunset-ridge").read_bytes() == _image(RED)
    assert workspace.design_file("sunset-ridge-2").read_bytes() == _image(BLUE)


def test_the_same_file_again_is_the_design_already_there(workspace: Workspace) -> None:
    save_listing_design(workspace, "sunset-ridge.png", _image(RED))
    save_listing_design(workspace, "sunset-ridge.png", _image(BLUE))

    assert save_listing_design(workspace, "sunset-ridge.png", _image(BLUE)) == "sunset-ridge-2"
    assert "sunset-ridge-3.png" not in _designs(workspace)


@pytest.mark.parametrize("filename", ["", "../../evil.png", "nested/evil.png", ".png"])
def test_a_name_that_cannot_be_saved_under_is_refused_and_nothing_written(
    workspace: Workspace, filename: str
) -> None:
    before = _designs(workspace)
    with pytest.raises(ListingDesignUploadRefused):
        save_listing_design(workspace, filename, _image(RED))
    assert _designs(workspace) == before


def test_bytes_that_are_not_an_image_are_refused(workspace: Workspace) -> None:
    before = _designs(workspace)
    with pytest.raises(ListingDesignUploadRefused, match="not a readable image"):
        save_listing_design(workspace, "notes.png", b"not a png")
    assert _designs(workspace) == before


def test_an_image_that_is_not_a_png_is_refused(workspace: Workspace) -> None:
    before = _designs(workspace)
    with pytest.raises(ListingDesignUploadRefused, match="must be PNG files"):
        save_listing_design(workspace, "photo.jpg", _image(RED, format="JPEG"))
    assert _designs(workspace) == before
