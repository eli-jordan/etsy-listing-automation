"""One rule for "a picture small enough to put in a list".

Two routers need it -- ``templates.py`` for the calibrator's rail and
``listings.py`` for the listings table, its hover card and the editor's
design strip -- and it is one decision, not two: how wide, and rendered per
request rather than cached on disk.

Deliberately not in :mod:`etsy_listings.ui.api.imagecache`, which answers the
different question of what the *preview loop* needs held in memory between
frames. Nothing here is cached in-process at all; see :func:`thumbnail_response`
for why.
"""

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

    Regenerated per request rather than cached on disk: the resize is cheap
    next to the response, and a cache in the workspace would be one more
    derived directory to invalidate. Repeat loads are handled by the
    ``Cache-Control`` header instead -- ``no-cache`` means "revalidate", not
    "do not store", which is what lets a re-exported design or a replaced
    mockup photo show up without a hard refresh.
    """
    buffer = BytesIO()
    with Image.open(source) as img:
        # RGBA, not RGB: a design's transparent background has no colour of
        # its own, and flattening onto RGB bakes it to opaque black (PIL's
        # default fill) instead of leaving it for the `<img>`'s own CSS
        # background to show through.
        flattened = img.convert("RGBA")
        flattened.thumbnail((THUMBNAIL_MAX, THUMBNAIL_MAX))
        flattened.save(buffer, format="PNG")
    return Response(
        content=buffer.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "no-cache"},
    )
