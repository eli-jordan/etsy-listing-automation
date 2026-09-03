"""The renderer's I/O boundary: loading design/template images and saving
results. Deliberately kept out of :mod:`etsy_listings.render.pipeline` so the
render passes themselves stay pure (A7)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from etsy_listings.render.passes import RGB, RGBA


class DesignValidationError(ValueError):
    """PRD validation: design files must be RGB with an alpha channel, never
    auto-converted -- a design without one is a config mistake to report, not
    silently paper over."""


def load_design(path: Path) -> RGBA:
    image = Image.open(path)
    if image.mode != "RGBA":
        raise DesignValidationError(
            f"{path}: design must be RGBA (has an alpha channel); got mode {image.mode!r}"
        )
    array: RGBA = np.array(image, dtype=np.uint8)
    return array


def load_template_base(path: Path) -> RGB:
    image = Image.open(path).convert("RGB")
    array: RGB = np.array(image, dtype=np.uint8)
    return array


def save_png(image: Image.Image, path: Path) -> None:
    """Deterministic PNG encode: 8-bit sRGB, no ``pnginfo`` (so no ``tIME`` or
    other timestamp/metadata chunk enters the file), fixed compression level so
    the same pixels always produce the same bytes on a given Pillow version --
    across versions, a changed byte stream is a real output-hash change the PRD
    wants visible (risk 9), not something to paper over here.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if image.mode != "RGB":
        image = image.convert("RGB")
    image.save(path, format="PNG", optimize=False, compress_level=6, pnginfo=None)
