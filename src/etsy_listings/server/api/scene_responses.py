"""A finished scene as an HTTP response, shared by the calibrator's and the
listing editors' preview routes.

Core answers with the picture (:mod:`etsy_listings.core.application.scene_previews`);
this is what only serving a browser needs. A rendered scene's ETag is its
identity, so a browser holding that picture is answered ``304`` without the
body, and a prepared one also carries the identities that let the editor promote
it. A frame is encoded here as WebP.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Literal

from fastapi.responses import Response

from etsy_listings.core.application.scene_previews import RenderedScene, SceneFrame, ScenePicture

PreviewScale = Literal["editor", "full"]
"""How big a preview to render.

Two named sizes, not a pixel count from the client. ``full`` is the photo's
own resolution -- what ``apply`` will write, and what the Preview tab shows
when you have stopped adjusting and started judging. ``editor`` is the
downscale the canvas drags against, capped at
:data:`~etsy_listings.server.api.imagecache.EDITOR_MAX_EDGE`.

Naming the sizes rather than accepting an ``?max_edge=`` keeps the number the
server's business: each distinct base size grows its own pair of cached
derived maps in the template's ``_renderer/derived/``, so a client free to ask for any
width would quietly fill that directory with one pair per window size.
"""


@dataclass(frozen=True)
class PreviewQuery:
    """The query parameters every saved-scene preview takes: the depicted
    ``colour`` (colour-matrix scenes) and the raster ``scale``."""

    colour: str | None = None
    scale: PreviewScale = "full"


@dataclass(frozen=True)
class ScenePreviewQuery(PreviewQuery):
    """A listing scene's preview query. ``v`` is a cache-buster the editor
    sends -- a signature of the saved design -- and is otherwise ignored."""

    v: str | None = None


EDITOR_MEDIA_TYPE = "image/webp"
"""What an editor frame comes back as.

``encode_png``'s determinism (fixed compression level, no metadata chunks)
exists so a render's bytes can be hashed and compared against the last applied
ones. An editor frame is looked at once and thrown away, so it buys nothing
there -- and PNG's entropy coding is the single most expensive step in
producing one. WebP at this quality is visually indistinguishable for judging
placement, and roughly an order of magnitude cheaper to encode and to send.

A ``full`` preview stays PNG: that one *is* meant to be the output you are
approving, so it should not be the only image in the loop that has been
through a lossy codec.
"""

EDITOR_WEBP_QUALITY = 88
EDITOR_WEBP_METHOD = 1
"""Encoder effort, 0 (fastest) to 6. Low on purpose: this runs inside the
frame budget of a drag, and the few percent of file size a higher setting
saves costs more milliseconds than the transfer does over loopback."""


def _frame_response(frame: SceneFrame) -> Response:
    buffer = BytesIO()
    frame.image.save(buffer, format="WEBP", quality=EDITOR_WEBP_QUALITY, method=EDITOR_WEBP_METHOD)
    response = Response(content=buffer.getvalue(), media_type=EDITOR_MEDIA_TYPE)
    if frame.interactive:
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Preview-Quality"] = "interactive"
    return response


def _identity_headers(scene: RenderedScene) -> dict[str, str]:
    headers = {
        "ETag": f'"{scene.render_identity}"',
        "X-Render-Identity": scene.render_identity,
        "Cache-Control": "no-cache",
    }
    if scene.generation_id is not None:
        headers["X-Map-Generation"] = scene.generation_id
    if scene.config_revision is not None:
        headers["X-Calibration-Revision"] = scene.config_revision
    return headers


def scene_response(picture: ScenePicture, *, if_none_match: str | None = None) -> Response:
    """``picture`` as a response; ``304`` when ``if_none_match`` names it."""
    if isinstance(picture, SceneFrame):
        return _frame_response(picture)
    headers = _identity_headers(picture)
    if if_none_match == headers["ETag"]:
        return Response(status_code=304, headers=headers)
    return Response(picture.png, media_type="image/png", headers=headers)
