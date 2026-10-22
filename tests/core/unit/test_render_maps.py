from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from etsy_listings.core.render.maps import DerivedMapCache, height_map, luminance_map

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


# A single bright pixel on black, far enough from every edge that a 13x13
# kernel never reaches the border: the blurred field stays exactly 0 there, so
# normalisation maps the far corner to 0 and the impulse centre to 1.
IMPULSE_CENTRE = 20
IMPULSE_RGB = np.zeros((41, 41, 3), dtype=np.uint8)
IMPULSE_RGB[IMPULSE_CENTRE, IMPULSE_CENTRE] = 255


def _gaussian_neighbour_ratio(ksize: int) -> float:
    """OpenCV's documented sigma for ``sigmaX=0`` (getGaussianKernel):
    ``0.3 * ((ksize - 1) * 0.5 - 1) + 0.8``. Normalised to the peak, the
    pixel one step from an impulse is ``exp(-1 / (2 sigma^2))``. Kernels of
    9 and below come from OpenCV's fixed tables instead, so these examples
    stay at 11 and above."""
    sigma = 0.3 * ((ksize - 1) * 0.5 - 1) + 0.8
    return float(np.exp(-1.0 / (2.0 * sigma**2)))


def test_height_map_spreads_an_impulse_by_the_gaussian_it_names() -> None:
    lum = luminance_map(IMPULSE_RGB)
    height = height_map(IMPULSE_RGB, blur_ksize=11)
    c = IMPULSE_CENTRE

    # Luminance keeps the impulse sharp; the height field must not.
    assert lum[c, c + 1] == 0.0
    assert height[c, c] == 1.0
    assert height[c, c + 1] == pytest.approx(_gaussian_neighbour_ratio(11), rel=1e-4)
    assert height[c + 1, c] == pytest.approx(_gaussian_neighbour_ratio(11), rel=1e-4)
    assert height[0, 0] == 0.0


def test_height_map_rounds_an_even_kernel_up_to_the_next_odd_one() -> None:
    even = height_map(IMPULSE_RGB, blur_ksize=12)
    c = IMPULSE_CENTRE

    assert np.array_equal(even, height_map(IMPULSE_RGB, blur_ksize=13))
    assert even[c, c + 1] == pytest.approx(_gaussian_neighbour_ratio(13), rel=1e-4)
    assert even[c, c + 1] != pytest.approx(_gaussian_neighbour_ratio(11), rel=1e-3)


def test_derived_map_cache_loads_what_it_stored_instead_of_recomputing(tmp_path: Path) -> None:
    derived = tmp_path / "_derived"
    cache = DerivedMapCache(derived)
    cache.luminance("black", GRADIENT_RGB)
    [stored] = derived.glob("*.npy")

    # Replace the stored map with valid but distinguishable data: only a
    # cache that actually reads its file can hand this back, and only one
    # that leaves a hit alone keeps it on disk.
    planted = np.full((64, 64), 0.25, dtype=np.float32)
    np.save(stored, planted)

    assert np.array_equal(cache.luminance("black", GRADIENT_RGB), planted)
    assert np.array_equal(np.load(stored), planted)
    assert list(derived.glob("*.npy")) == [stored]


def test_derived_map_cache_invalidates_on_source_change(tmp_path: Path) -> None:
    cache = DerivedMapCache(tmp_path / "_derived")
    cache.luminance("black", GRADIENT_RGB)

    # Different bytes are a different key: the flat image's own answer, not
    # the gradient's cached one.
    assert np.allclose(cache.luminance("black", FLAT), 0.5)
    assert len(list((tmp_path / "_derived").glob("*.npy"))) == 2


def test_derived_map_cache_invalidates_on_kernel_change(tmp_path: Path) -> None:
    cache = DerivedMapCache(tmp_path / "_derived")
    c = IMPULSE_CENTRE
    cache.height("black", IMPULSE_RGB, blur_ksize=11)

    wider = cache.height("black", IMPULSE_RGB, blur_ksize=13)

    assert wider[c, c + 1] == pytest.approx(_gaussian_neighbour_ratio(13), rel=1e-4)
    assert len(list((tmp_path / "_derived").glob("*.npy"))) == 2
