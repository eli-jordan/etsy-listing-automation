"""``render_scene`` and ``export_many`` work only where a layer prints, and
that must not change a single pixel: the reference here is the same
arithmetic over the whole canvas."""

from __future__ import annotations

import numpy as np

from etsy_listings.core.render.config import Point, RenderConfig, ShadeConfig
from etsy_listings.core.render.passes import export_many, shade, warp
from etsy_listings.core.render.pipeline import Layer, render_scene

CANVAS = 96


def _noise(shape: tuple[int, ...], seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 256, shape, dtype=np.uint8)


def _layer_printing_in(top: int, left: int, size: int, seed: int) -> np.ndarray:
    """Canvas-sized RGBA: partial alpha inside the square, zero alpha outside
    it over colour that is not black, so ignoring the outside is observable
    only if the arithmetic there was not a no-op."""
    layer = _noise((CANVAS, CANVAS, 4), seed)
    alpha = np.zeros((CANVAS, CANVAS), np.uint8)
    alpha[top : top + size, left : left + size] = _noise((size, size), seed + 1)
    layer[..., 3] = alpha
    return layer


def _whole_canvas_fold(base: np.ndarray, layers: list[np.ndarray]) -> np.ndarray:
    composite = base.astype(np.float32)
    for layer in layers:
        alpha = layer[..., 3:4].astype(np.float32) / 255.0
        composite = composite * (1 - alpha) + layer[..., :3].astype(np.float32) * alpha
    return np.clip(composite + 0.5, 0, 255).astype(np.uint8)


def test_export_many_matches_compositing_the_whole_canvas() -> None:
    base = _noise((CANVAS, CANVAS, 3), 1)
    layers = [_layer_printing_in(10, 12, 30, 2), _layer_printing_in(40, 50, 40, 4)]

    assert np.array_equal(np.array(export_many(base, layers)), _whole_canvas_fold(base, layers))


def test_export_many_with_layers_that_print_nothing_leaves_base_unchanged() -> None:
    base = _noise((CANVAS, CANVAS, 3), 1)
    blank = _noise((CANVAS, CANVAS, 4), 2)
    blank[..., 3] = 0

    assert np.array_equal(np.array(export_many(base, [blank])), base)


def test_render_scene_matches_shading_and_compositing_the_whole_canvas() -> None:
    base = _noise((CANVAS, CANVAS, 3), 1)
    luminance = np.random.default_rng(3).random((CANVAS, CANVAS), dtype=np.float32)
    quads = [
        (
            Point(x=20.5, y=14.2),
            Point(x=70.1, y=19.8),
            Point(x=66.3, y=75.4),
            Point(x=15.9, y=70.0),
        ),
        (
            Point(x=60.0, y=60.0),
            Point(x=90.0, y=62.0),
            Point(x=88.0, y=90.0),
            Point(x=58.0, y=88.0),
        ),
    ]
    layers = [
        Layer(
            design=_noise((40, 32, 4), 5 + i),
            cfg=RenderConfig(
                bounding_box=quad,
                shade=ShadeConfig(enabled=True, opacity=0.6, blend="soft-light"),
            ),
        )
        for i, quad in enumerate(quads)
    ]

    expected = _whole_canvas_fold(
        base,
        [
            shade(
                warp(layer.design, layer.cfg.bounding_box, (CANVAS, CANVAS)),
                layer.cfg.shade,
                luminance,
            )
            for layer in layers
        ],
    )

    assert np.array_equal(np.array(render_scene(base, layers, luminance=luminance)), expected)
