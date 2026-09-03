"""The array vocabulary the renderer speaks.

Every pass, map and I/O function in ``render/`` is typed in these terms, so
they live in their own module rather than in whichever one happened to define
them first. Colour handling is fixed at 8-bit sRGB throughout (A7's
determinism controls): ``RGBA`` wherever alpha matters -- the design and the
print layer derived from it -- and ``RGB`` for the opaque mockup photo.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

RGB = NDArray[np.uint8]
"""Opaque 8-bit sRGB image, shape (h, w, 3)."""

RGBA = NDArray[np.uint8]
"""8-bit sRGB image with straight (non-premultiplied) alpha, shape (h, w, 4)."""

FloatMap = NDArray[np.float32]
"""Single-channel map normalised to [0, 1] -- a luminance or height field."""
