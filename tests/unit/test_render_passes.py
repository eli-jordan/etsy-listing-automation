from __future__ import annotations

import numpy as np

from etsy_listings.render.config import DisplaceConfig, Point, ShadeConfig
from etsy_listings.render.passes import displace, export, export_many, shade, warp

IDENTITY_QUAD = (
    Point(x=0.0, y=0.0),
    Point(x=63.0, y=0.0),
    Point(x=63.0, y=63.0),
    Point(x=0.0, y=63.0),
)


def _solid_rgba(size: int, rgba: tuple[int, int, int, int]) -> np.ndarray:
    array = np.zeros((size, size, 4), dtype=np.uint8)
    array[..., 0] = rgba[0]
    array[..., 1] = rgba[1]
    array[..., 2] = rgba[2]
    array[..., 3] = rgba[3]
    return array


def test_warp_identity_quad_preserves_solid_colour() -> None:
    design = _solid_rgba(64, (200, 50, 50, 255))
    result = warp(design, IDENTITY_QUAD, (64, 64))
    # Interior pixels should be untouched by an (almost) identity transform;
    # only edge pixels may differ due to interpolation/rounding.
    interior = result[10:54, 10:54]
    assert np.all(interior[..., 0] == 200)
    assert np.all(interior[..., 3] == 255)


def test_warp_output_matches_requested_canvas_size() -> None:
    design = _solid_rgba(20, (1, 2, 3, 255))
    result = warp(design, IDENTITY_QUAD, (100, 80))
    assert result.shape == (80, 100, 4)


def test_displace_disabled_is_a_no_op() -> None:
    img = _solid_rgba(32, (10, 20, 30, 255))
    height = np.zeros((32, 32), dtype=np.float32)
    result = displace(img, DisplaceConfig(enabled=False, strength=1.0), height)
    assert np.array_equal(result, img)


def test_displace_zero_strength_is_a_no_op() -> None:
    img = _solid_rgba(32, (10, 20, 30, 255))
    height = np.random.default_rng(0).random((32, 32)).astype(np.float32)
    result = displace(img, DisplaceConfig(enabled=True, strength=0.0), height)
    assert np.array_equal(result, img)


def test_displace_flat_height_field_is_a_no_op() -> None:
    img = _solid_rgba(32, (10, 20, 30, 255))
    flat_height = np.full((32, 32), 0.5, dtype=np.float32)  # zero gradient
    result = displace(img, DisplaceConfig(enabled=True, strength=1.0), flat_height)
    assert np.array_equal(result, img)


def test_shade_disabled_is_a_no_op() -> None:
    img = _solid_rgba(16, (100, 100, 100, 255))
    lum = np.zeros((16, 16), dtype=np.float32)
    result = shade(img, ShadeConfig(enabled=False), lum)
    assert np.array_equal(result, img)


def test_shade_preserves_alpha_channel() -> None:
    img = _solid_rgba(16, (100, 100, 100, 128))
    lum = np.full((16, 16), 1.0, dtype=np.float32)
    result = shade(img, ShadeConfig(enabled=True, opacity=1.0, blend="multiply"), lum)
    assert np.all(result[..., 3] == 128)


def test_shade_multiply_darkens_toward_black_luminance() -> None:
    img = _solid_rgba(16, (200, 200, 200, 255))
    lum = np.zeros((16, 16), dtype=np.float32)  # black shadow
    result = shade(img, ShadeConfig(enabled=True, opacity=1.0, blend="multiply"), lum)
    assert np.all(result[..., 0] < 10)


def test_export_zero_alpha_leaves_base_unchanged() -> None:
    base = np.full((8, 8, 3), 50, dtype=np.uint8)
    layer = _solid_rgba(8, (255, 0, 0, 0))
    result = export(base, layer)
    assert np.array_equal(np.array(result), base)


def test_export_full_alpha_shows_print_layer() -> None:
    base = np.full((8, 8, 3), 50, dtype=np.uint8)
    layer = _solid_rgba(8, (255, 0, 0, 255))
    result = export(base, layer)
    result_array = np.array(result)
    assert np.all(result_array[..., 0] == 255)
    assert np.all(result_array[..., 1] == 0)


def test_export_returns_rgb_image() -> None:
    base = np.zeros((4, 4, 3), dtype=np.uint8)
    layer = _solid_rgba(4, (0, 0, 0, 0))
    result = export(base, layer)
    assert result.mode == "RGB"
    assert result.size == (4, 4)


def test_export_many_with_no_layers_leaves_base_unchanged() -> None:
    base = np.full((8, 8, 3), 50, dtype=np.uint8)
    result = export_many(base, [])
    assert np.array_equal(np.array(result), base)


def test_export_many_with_one_layer_matches_export() -> None:
    """The single-layer path through export_many must be byte-identical to
    export() -- this is what keeps colour-matrix/single kind output
    (which calls export() directly) unaffected by the multiple-kind addition."""
    base = np.full((8, 8, 3), 50, dtype=np.uint8)
    layer = _solid_rgba(8, (255, 0, 0, 180))
    assert np.array_equal(np.array(export_many(base, [layer])), np.array(export(base, layer)))


def test_export_many_folds_layers_in_order() -> None:
    base = np.full((8, 8, 3), 0, dtype=np.uint8)
    red = _solid_rgba(8, (255, 0, 0, 255))
    blue = _solid_rgba(8, (0, 0, 255, 255))
    result = np.array(export_many(base, [red, blue]))
    # blue is later in the list, so it's composited last and wins where they overlap
    assert np.all(result[..., 2] == 255)
    assert np.all(result[..., 0] == 0)
