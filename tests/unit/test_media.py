"""`config/media.py`: what kind of thing each `media:` entry is (PRD 71).

The gallery rules and the video gate both start from this one answer, so it
is tested on its own: a template entry is always an image, and a file ref is
an image or a video by its extension alone.
"""

from __future__ import annotations

import pytest

from etsy_listings.config.media import TemplateMediaEntry, UnknownMediaTypeError, media_kind


def test_a_template_entry_is_an_image() -> None:
    assert media_kind(TemplateMediaEntry(template="flat-lay-01", colour="black")) == "image"


def test_a_template_entry_without_a_colour_is_an_image() -> None:
    assert media_kind(TemplateMediaEntry(template="colour-chart-01")) == "image"


@pytest.mark.parametrize(
    "ref", ["common-media/size-guide.png", "./shots/back.jpg", "common-media/care.jpeg"]
)
def test_a_png_or_jpeg_ref_is_an_image(ref: str) -> None:
    assert media_kind(ref) == "image"


@pytest.mark.parametrize("ref", ["common-media/size-guide.mp4", "./close-up.mov"])
def test_an_mp4_or_mov_ref_is_a_video(ref: str) -> None:
    assert media_kind(ref) == "video"


def test_the_extension_is_matched_case_insensitively() -> None:
    """A phone names its clips `IMG_1234.MOV`; the file is no less a video."""
    assert media_kind("./IMG_1234.MOV") == "video"
    assert media_kind("common-media/SIZE.PNG") == "image"


@pytest.mark.parametrize("ref", ["common-media/size-guide.gif", "common-media/README", "./a.webm"])
def test_an_unknown_extension_is_refused_by_name(ref: str) -> None:
    with pytest.raises(UnknownMediaTypeError) as exc_info:
        media_kind(ref)
    message = str(exc_info.value)
    assert ref in message
    assert ".png" in message and ".mp4" in message
