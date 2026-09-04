"""Sampling a representative garment colour out of a mockup photo.

Not a render pass -- nothing composited depends on it -- but pure in the same
sense (A7): ndarrays and frozen config in, a tuple out, no I/O and no clock.
``apply`` uses it to put a colour block next to each render log line, so a run
reads as the colour set it produced rather than as a list of slugs.

The sample is taken from the *blank* mockup inside the print area, which is
where the garment fills the frame most reliably -- the median rather than the
mean, so a fold shadow or a highlight cannot drag the result away from the
fabric colour.
"""

from __future__ import annotations

import math

import numpy as np

from etsy_listings.render.config import BoundingBox
from etsy_listings.render.types import RGB


def sample_swatch(base: RGB, box: BoundingBox) -> tuple[int, int, int]:
    height, width = base.shape[:2]
    xs = [point.x for point in box]
    ys = [point.y for point in box]

    x0 = max(0, min(width - 1, int(math.floor(min(xs)))))
    x1 = max(x0 + 1, min(width, int(math.ceil(max(xs)))))
    y0 = max(0, min(height - 1, int(math.floor(min(ys)))))
    y1 = max(y0 + 1, min(height, int(math.ceil(max(ys)))))

    region = base[y0:y1, x0:x1].reshape(-1, 3)
    median = np.median(region, axis=0)
    red, green, blue = (int(round(float(channel))) for channel in median)
    return red, green, blue
