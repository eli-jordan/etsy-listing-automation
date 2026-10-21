"""The renderer's I/O boundary: loading design/template images and saving
results. Deliberately kept out of:mod:`etsy_listings.core.render.pipeline` so the
render passes themselves stay pure."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image

from etsy_listings.core.render.types import RGB, RGBA

MARIGOLD_PNG_COMPRESSION = 1


class DesignValidationError(ValueError):
    """Validation: design files must be RGB with an alpha channel, never
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


def encode_png(image: Image.Image, *, compression: int = 6) -> bytes:
    """Deterministic PNG encode: 8-bit sRGB, no ``pnginfo`` (so no ``tIME`` or
    other timestamp/metadata chunk enters the file), fixed compression level so
    the same pixels always produce the same bytes on a given Pillow version --
    across versions, a changed byte stream is a real output-hash change that must remain visible,
    not something to paper over here.
    """
    if image.mode != "RGB":
        image = image.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=compression, pnginfo=None)
    return buffer.getvalue()


def save_png(image: Image.Image, path: Path, *, compression: int = 6) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_png(image, compression=compression))
