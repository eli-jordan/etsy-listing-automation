"""What a `media:` entry is: the gallery's two shapes and two kinds (PRD 71).

`media:` is the listing's Etsy gallery, in the order a buyer sees it. It holds
two *shapes* -- a ``{template, colour}`` entry the tool renders, and a bare
file ref (PRD 72's two roots) uploaded as-is -- and two *kinds*, image and
video. The shape is the model's; the kind is answered here, once, because the
gallery rules in `Listing`, the video gate in `listing_validation` and the
Etsy media stage all start from it.

A template entry is always an image: a render is a PNG. A file ref is an image
or a video by its extension alone -- no file is opened, so this stays pure and
answers the same for a draft that is on disk nowhere. An extension outside the
two lists is refused rather than guessed at, since Etsy's help page names
exactly these formats and anything else would be discovered as a failed upload.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

MediaKind = Literal["image", "video"]

IMAGE_EXTENSIONS: Final = (".png", ".jpg", ".jpeg")
VIDEO_EXTENSIONS: Final = (".mp4", ".mov")
"""PRD 71. Matched case-insensitively: a phone names its clips ``IMG_1234.MOV``."""

MAX_IMAGES: Final = 20
"""Etsy's image cap per listing. Separate from :data:`MAX_VIDEOS`, because
Etsy counts the two apart -- a listing may hold 20 images *and* 2 videos."""
MAX_VIDEOS: Final = 2
"""Etsy's video cap per listing, with ``is_multi_video=true`` (PRD 71)."""
FEATURED_VIDEO_POSITION: Final = 2
"""Where Etsy pins the featured video, behind the thumbnail (decision 9).
1-based, as a buyer counts the gallery."""


class TemplateMediaEntry(BaseModel):
    """Always-explicit template reference -- there is no bare-colour
    shorthand. ``colour`` is required when the referenced template is
    ``colour-matrix`` kind (which colour's photo) and must be omitted for
    ``multiple``/``single`` kind (exactly one output each, nothing to
    disambiguate)."""

    model_config = ConfigDict(extra="forbid")

    template: str
    colour: str | None = None


MediaEntry = TemplateMediaEntry | str
"""Either an explicit template reference, or a file ref (PRD 72's two roots:
no prefix for the workspace, ``./`` for the listing's own directory)."""


class UnknownMediaTypeError(ValueError):
    """A file ref whose extension is neither an image's nor a video's."""

    def __init__(self, ref: str) -> None:
        allowed = ", ".join((*IMAGE_EXTENSIONS, *VIDEO_EXTENSIONS))
        super().__init__(
            f"media entry {ref!r} is not a file type Etsy accepts; use one of {allowed}"
        )


def media_kind(entry: MediaEntry) -> MediaKind:
    """``"image"`` or ``"video"``; :class:`UnknownMediaTypeError` otherwise."""
    if isinstance(entry, TemplateMediaEntry):
        return "image"
    suffix = PurePosixPath(entry).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    raise UnknownMediaTypeError(entry)
