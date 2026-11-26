"""What a `media:` entry is: a rendered ``{template, colour}`` or a file ref,
and whether it is an image or a video.

A file ref's kind is read from its extension alone, so the answer is pure. An
extension outside the two lists is refused: Etsy accepts exactly these formats,
and anything else would surface only as a failed upload.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

MediaKind = Literal["image", "video"]

IMAGE_EXTENSIONS: Final = (".png", ".jpg", ".jpeg")
VIDEO_EXTENSIONS: Final = (".mp4", ".mov")
"""ADR-0045. Matched case-insensitively: a phone names its clips ``IMG_1234.MOV``."""

MAX_IMAGES: Final = 20
"""Etsy's image cap per listing. Separate from :data:`MAX_VIDEOS`, because
Etsy counts the two apart -- a listing may hold 20 images *and* 2 videos."""
MAX_VIDEOS: Final = 2
"""Etsy's video cap per listing, with ``is_multi_video=true``."""
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
"""Either an explicit template reference, or a file ref (ADR-0046's two roots:
no prefix for the workspace, ``./`` for the listing's own directory)."""


class UnknownMediaTypeError(ValueError):
    def __init__(self, ref: str) -> None:
        allowed = ", ".join((*IMAGE_EXTENSIONS, *VIDEO_EXTENSIONS))
        super().__init__(
            f"media entry {ref!r} is not a file type Etsy accepts; use one of {allowed}"
        )


def media_kind(entry: MediaEntry) -> MediaKind:
    if isinstance(entry, TemplateMediaEntry):
        return "image"
    suffix = PurePosixPath(entry).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    raise UnknownMediaTypeError(entry)


@dataclass(frozen=True)
class VideoFacts:
    """The facts Etsy's help page sets video limits on."""

    size_bytes: int
    duration_seconds: float
    width: int
    height: int
    has_audio: bool


@dataclass(frozen=True)
class ProbeFailure:
    """``reason`` follows the file's name in a sentence."""

    reason: str
