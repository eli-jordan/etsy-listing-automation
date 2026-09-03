from __future__ import annotations

from pathlib import Path

import numpy as np

from etsy_listings.render.maps import DerivedMapCache, height_map, luminance_map

GRADIENT = np.tile(np.linspace(0, 255, 64, dtype=np.uint8), (64, 1))
GRADIENT_RGB = np.stack([GRADIENT] * 3, axis=-1)

FLAT = np.full((32, 32, 3), 128, dtype=np.uint8)


def test_luminance_map_normalises_to_full_range() -> None:
    result = luminance_map(GRADIENT_RGB)
    assert result.min() == 0.0
    assert result.max() == 1.0
    assert result.dtype == np.float32


def test_luminance_map_flat_image_returns_mid_grey() -> None:
    result = luminance_map(FLAT)
    assert np.allclose(result, 0.5)


def test_height_map_is_smoother_than_luminance() -> None:
    lum = luminance_map(GRADIENT_RGB)
    height = height_map(GRADIENT_RGB, blur_ksize=9)
    # Both normalise to [0, 1] but the blur should reduce local variance.
    assert np.var(np.diff(height, axis=1)) <= np.var(np.diff(lum, axis=1)) + 1e-6


def test_height_map_accepts_even_ksize_by_rounding_up() -> None:
    # cv2.GaussianBlur requires an odd kernel; this must not raise.
    height_map(GRADIENT_RGB, blur_ksize=10)


def test_derived_map_cache_writes_and_reuses(tmp_path: Path) -> None:
    cache = DerivedMapCache(tmp_path / "_derived")
    first = cache.luminance("black", GRADIENT_RGB)
    files_after_first = list((tmp_path / "_derived").glob("*.npy"))
    assert len(files_after_first) == 1

    second = cache.luminance("black", GRADIENT_RGB)
    files_after_second = list((tmp_path / "_derived").glob("*.npy"))

    assert np.array_equal(first, second)
    assert len(files_after_second) == 1  # no new file written on cache hit


def test_derived_map_cache_invalidates_on_source_change(tmp_path: Path) -> None:
    cache = DerivedMapCache(tmp_path / "_derived")
    cache.luminance("black", GRADIENT_RGB)
    cache.luminance("black", FLAT)  # different bytes -> different cache key
    files = list((tmp_path / "_derived").glob("*.npy"))
    assert len(files) == 2
