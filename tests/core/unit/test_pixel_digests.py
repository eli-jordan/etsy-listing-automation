"""``PixelDigests``: a file's pixel digest is computed once while the file is
unchanged, even when its pixels are decoded again to compose a new scene."""

from __future__ import annotations

import os

import numpy as np
import pytest
from PIL import Image

from etsy_listings.core.preparation import scene_cache
from etsy_listings.core.preparation.scene_cache import PixelDigests


@pytest.fixture
def digests(monkeypatch) -> list[int]:
    """Counts every design digest computed, still computing it for real."""
    calls: list[int] = []
    real = scene_cache.artwork_identity

    def counting(pixels):
        calls.append(1)
        return real(pixels)

    monkeypatch.setattr(scene_cache, "artwork_identity", counting)
    return calls


def _write(path, colour: str) -> None:
    Image.new("RGBA", (8, 8), colour).save(path)


def test_decoding_an_unchanged_file_again_reuses_its_digest(tmp_path, digests) -> None:
    path = tmp_path / "design.png"
    _write(path, "red")
    memo = PixelDigests()

    first_pixels, first = memo.decode_design(path)
    again_pixels, again = memo.decode_design(path)

    assert len(digests) == 1
    assert again == first
    assert np.array_equal(again_pixels, first_pixels)


def test_a_file_written_since_is_digested_again(tmp_path, digests) -> None:
    path = tmp_path / "design.png"
    _write(path, "red")
    memo = PixelDigests()
    _, first = memo.decode_design(path)

    _write(path, "blue")
    stamp = path.stat().st_mtime_ns + 1_000_000_000
    os.utime(path, ns=(stamp, stamp))
    _, again = memo.decode_design(path)

    assert len(digests) == 2
    assert again != first
