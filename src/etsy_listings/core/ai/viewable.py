"""The copy of a design an AI provider actually looks at.

A print design is usually a PNG with a transparent background, and the
provider CLIs flatten transparency onto black before the model sees it. Black
artwork on a transparent ground then reaches the model as a solid black
square, and a brief drafted from it says there is nothing there. So before
any provider is handed a design, its transparent pixels are composited onto a
background that contrasts with the artwork itself: white behind dark
artwork, charcoal behind light artwork.

The flattened copy is written inside the workspace cache rather than a
temporary directory, because `claude -p` reads the image with its own Read
tool and is not given access to anything outside the workspace
(`ai/claude.py`). It keeps the design's file name, so a run step still says
which design it is reading, under a directory named by the source's content
hash, so an edited design is never served a stale copy.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Final

from PIL import Image, ImageStat

LIGHT_BACKGROUND: Final = (255, 255, 255)
DARK_BACKGROUND: Final = (34, 34, 34)
_DARK_ARTWORK_LUMINANCE: Final = 128
"""Below this alpha-weighted mean luminance the artwork reads as dark, and
gets :data:`LIGHT_BACKGROUND`."""


def viewable_design(source: Path, cache_dir: Path) -> Path:
    """``source`` itself when it has no transparency, otherwise a flattened
    copy of it under ``cache_dir``."""
    with Image.open(source) as image:
        if not _has_transparency(image):
            return source
        rgba = image.convert("RGBA")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
    target = cache_dir / digest / source.name
    if target.is_file():
        return target
    background = Image.new("RGBA", rgba.size, _background_for(rgba) + (255,))
    flattened = Image.alpha_composite(background, rgba).convert("RGB")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    flattened.save(partial, format="PNG")
    os.replace(partial, target)
    return target


def _has_transparency(image: Image.Image) -> bool:
    if image.mode == "P":
        return "transparency" in image.info
    if image.mode not in ("RGBA", "LA", "PA"):
        return False
    low = ImageStat.Stat(image.getchannel("A")).extrema[0][0]
    return bool(low < 255)


def _background_for(rgba: Image.Image) -> tuple[int, int, int]:
    """Weight each pixel's luminance by its opacity, so a mostly transparent
    canvas is judged by its artwork rather than by its empty pixels' colour."""
    alpha = rgba.getchannel("A")
    coverage = ImageStat.Stat(alpha).mean[0]
    if coverage == 0:
        return LIGHT_BACKGROUND
    luminance = rgba.convert("L")
    weighted = ImageStat.Stat(Image.composite(luminance, Image.new("L", rgba.size, 0), alpha))
    mean = weighted.mean[0] * 255 / coverage
    return LIGHT_BACKGROUND if mean < _DARK_ARTWORK_LUMINANCE else DARK_BACKGROUND
