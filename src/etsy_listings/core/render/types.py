from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

RGB = NDArray[np.uint8]
"""Opaque 8-bit sRGB image, shape (h, w, 3)."""

RGBA = NDArray[np.uint8]
"""8-bit sRGB image with straight (non-premultiplied) alpha, shape (h, w, 4)."""

IMAGE_NDIM = 3
"""An ``RGB`` or ``RGBA`` array's dimensions: rows, columns, channels."""

RGB_CHANNELS = 3
RGBA_CHANNELS = 4

FloatMap = NDArray[np.float32]
"""Single-channel map normalised to [0, 1] -- a luminance or height field."""
