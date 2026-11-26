"""The copy of a design an AI provider actually looks at.

The provider CLIs flatten transparency onto black, so black artwork on a
transparent ground reaches the model as a black square. A transparent design
is therefore composited onto a background that contrasts with its artwork.

The copy lives in the workspace cache, not a temporary directory, because
`claude -p`'s Read tool cannot reach outside the workspace.
"""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path
from typing import Final

from PIL import Image, ImageStat

LIGHT_BACKGROUND: Final = (255, 255, 255)
DARK_BACKGROUND: Final = (34, 34, 34)
_DARK_ARTWORK_LUMINANCE: Final = 128
"""Below this alpha-weighted mean luminance the artwork reads as dark, and
gets :data:`LIGHT_BACKGROUND`."""
_OPAQUE: Final = 255  # 8-bit alpha of a fully opaque pixel


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
    background = Image.new("RGBA", rgba.size, (*_background_for(rgba), _OPAQUE))
    flattened = Image.alpha_composite(background, rgba).convert("RGB")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Runs share a process, so the partial name carries the thread too.
    partial = target.with_name(f"{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    flattened.save(partial, format="PNG")
    try:
        partial.replace(target)
    except PermissionError:
        # Windows refuses to replace a file another run has open; the copy
        # there has the same content.
        partial.unlink(missing_ok=True)
        if not target.is_file():
            raise
    return target


def _has_transparency(image: Image.Image) -> bool:
    if image.mode == "P":
        return "transparency" in image.info
    if image.mode not in ("RGBA", "LA", "PA"):
        return False
    low = ImageStat.Stat(image.getchannel("A")).extrema[0][0]
    return bool(low < _OPAQUE)


def _background_for(rgba: Image.Image) -> tuple[int, int, int]:
    """Contrast with the artwork's mean luminance, weighted by opacity."""
    alpha = rgba.getchannel("A")
    coverage = ImageStat.Stat(alpha).mean[0]
    if coverage == 0:
        return LIGHT_BACKGROUND
    luminance = rgba.convert("L")
    weighted = ImageStat.Stat(Image.composite(luminance, Image.new("L", rgba.size, 0), alpha))
    mean = weighted.mean[0] * 255 / coverage
    return LIGHT_BACKGROUND if mean < _DARK_ARTWORK_LUMINANCE else DARK_BACKGROUND
