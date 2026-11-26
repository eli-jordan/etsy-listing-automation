from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image

from etsy_listings.core.render.types import RGB, RGBA

MARIGOLD_PNG_COMPRESSION = 1


class DesignValidationError(ValueError): ...


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
    """No ``pnginfo``, so no ``tIME`` chunk: equal pixels give equal bytes on one Pillow."""
    if image.mode != "RGB":
        image = image.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=compression, pnginfo=None)
    return buffer.getvalue()


def save_png(image: Image.Image, path: Path, *, compression: int = 6) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_png(image, compression=compression))
