"""Sampling a representative garment colour out of a mockup photo: the median of
the blank mockup inside the print area, so a fold shadow or a highlight cannot
drag it off the fabric colour."""

from __future__ import annotations

import math

import numpy as np

from etsy_listings.core.render.config import BoundingBox
from etsy_listings.core.render.types import RGB


def sample_swatch(base: RGB, box: BoundingBox) -> tuple[int, int, int]:
    height, width = base.shape[:2]
    xs = [point.x for point in box]
    ys = [point.y for point in box]

    x0 = max(0, min(width - 1, math.floor(min(xs))))
    x1 = max(x0 + 1, min(width, math.ceil(max(xs))))
    y0 = max(0, min(height - 1, math.floor(min(ys))))
    y1 = max(y0 + 1, min(height, math.ceil(max(ys))))

    region = base[y0:y1, x0:x1].reshape(-1, 3)
    median = np.median(region, axis=0)
    red, green, blue = (round(float(channel)) for channel in median)
    return red, green, blue
