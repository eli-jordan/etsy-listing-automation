from __future__ import annotations

import numpy as np

from etsy_listings.render.config import Point
from etsy_listings.render.swatch import sample_swatch


def _box(x0: float, y0: float, x1: float, y1: float):
    return (
        Point(x=x0, y=y0),
        Point(x=x1, y=y0),
        Point(x=x1, y=y1),
        Point(x=x0, y=y1),
    )


def _canvas(fill: tuple[int, int, int], size: int = 40) -> np.ndarray:
    return np.full((size, size, 3), fill, dtype=np.uint8)


def test_samples_the_colour_inside_the_print_area() -> None:
    base = _canvas((10, 20, 30))
    base[8:32, 8:32] = (200, 100, 50)  # the garment, framed by a different background
    assert sample_swatch(base, _box(10, 10, 30, 30)) == (200, 100, 50)


def test_ignores_what_is_outside_the_bounding_box() -> None:
    base = _canvas((0, 0, 0))
    base[0:20, 0:40] = (255, 255, 255)
    assert sample_swatch(base, _box(0, 20, 40, 40)) == (0, 0, 0)


def test_median_not_mean_so_a_fold_shadow_cannot_drag_the_result() -> None:
    """A few very dark pixels are a shadow, not the fabric colour. The mean
    would move; the median must not."""
    base = _canvas((180, 180, 180))
    base[10:14, 10:30] = (0, 0, 0)
    assert sample_swatch(base, _box(10, 10, 30, 30)) == (180, 180, 180)


def test_a_box_reaching_past_the_image_is_clipped_not_an_error() -> None:
    base = _canvas((60, 70, 80), size=20)
    assert sample_swatch(base, _box(-50, -50, 500, 500)) == (60, 70, 80)


def test_a_box_entirely_outside_the_image_still_yields_a_colour() -> None:
    base = _canvas((5, 6, 7), size=20)
    assert sample_swatch(base, _box(100, 100, 140, 140)) == (5, 6, 7)
