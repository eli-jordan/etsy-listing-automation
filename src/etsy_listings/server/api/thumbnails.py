"""One rule for "a picture small enough to put in a list", shared by the
calibrator's rail and the listings pages; nothing here is cached."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi.responses import Response
from PIL import Image

THUMBNAIL_MAX = 160
"""Longest edge of a list thumbnail, in px. The calibrator's rail draws them
at ~26x30 CSS px (wireframe 2a) and the listings table at 30x30, so this
leaves headroom for a HiDPI screen without turning either list into a
megabyte of PNG."""


def thumbnail_response(source: Path) -> Response:
    """``source`` downscaled to :data:`THUMBNAIL_MAX`, as a PNG response.

    Rendered per request: the resize is cheap next to the response, and a disk
    cache would be one more derived directory to invalidate.
    """
    buffer = BytesIO()
    with Image.open(source) as img:
        small = img.convert("RGBA")
        small.thumbnail((THUMBNAIL_MAX, THUMBNAIL_MAX))
        small.save(buffer, format="PNG")
    return Response(
        content=buffer.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "no-cache"},
    )
