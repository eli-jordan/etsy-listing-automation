"""The list thumbnail every router serves: size, transparency and caching.

Subject: ``server.api.thumbnails.thumbnail_response``.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

from etsy_listings.server.api.thumbnails import THUMBNAIL_MAX, thumbnail_response


def _design(path: Path) -> Path:
    image = Image.new("RGBA", (800, 400), (0, 0, 0, 0))
    image.paste((200, 30, 30, 255), (300, 100, 500, 300))
    image.save(path)
    return path


def _decoded(source: Path) -> Image.Image:
    return Image.open(BytesIO(bytes(thumbnail_response(source).body)))


def test_a_thumbnail_fits_the_longest_edge_cap(tmp_path: Path) -> None:
    assert max(_decoded(_design(tmp_path / "design.png")).size) == THUMBNAIL_MAX


def test_a_transparent_background_stays_transparent_rather_than_black(tmp_path: Path) -> None:
    thumbnail = _decoded(_design(tmp_path / "design.png"))

    assert thumbnail.mode == "RGBA"
    assert thumbnail.getpixel((0, 0))[3] == 0


def test_a_thumbnail_is_revalidated_so_a_replaced_file_shows_without_a_hard_refresh(
    tmp_path: Path,
) -> None:
    response = thumbnail_response(_design(tmp_path / "design.png"))

    assert response.headers["cache-control"] == "no-cache"
