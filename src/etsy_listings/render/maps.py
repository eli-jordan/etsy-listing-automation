"""Derived height/luminance maps, and the ``_derived/`` disk cache for them.

Pure computation (:func:`luminance_map`, :func:`height_map`) is separated from
the cache (:class:`DerivedMapCache`), which is the one place in this module
that does I/O -- keeping the split lets the golden harness test the maps
without touching a filesystem.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from etsy_listings.render.passes import RGB, FloatMap


def luminance_map(base_rgb: RGB) -> FloatMap:
    """Desaturate -> normalise levels. PRD: "derived from the blank mockup's own
    luminance" -- this is why plain flat mockup PNGs are sufficient; no
    purchased displacement/lighting maps are needed."""
    gray = np.asarray(cv2.cvtColor(base_rgb, cv2.COLOR_RGB2GRAY), dtype=np.uint8)
    normalized = gray.astype(np.float32) / 255.0
    lo, hi = float(normalized.min()), float(normalized.max())
    if hi - lo < 1e-6:
        return np.full_like(normalized, 0.5)
    return (normalized - lo) / (hi - lo)


def height_map(base_rgb: RGB, blur_ksize: int = 15) -> FloatMap:
    """Gaussian-blurred luminance, used as the displacement height field."""
    gray = np.asarray(cv2.cvtColor(base_rgb, cv2.COLOR_RGB2GRAY), dtype=np.uint8)
    normalized = gray.astype(np.float32) / 255.0
    ksize = blur_ksize if blur_ksize % 2 == 1 else blur_ksize + 1
    blurred = np.asarray(
        cv2.GaussianBlur(normalized, (ksize, ksize), sigmaX=0, borderType=cv2.BORDER_REPLICATE),
        dtype=np.float32,
    )
    lo, hi = float(blurred.min()), float(blurred.max())
    if hi - lo < 1e-6:
        return np.full_like(blurred, 0.5)
    return (blurred - lo) / (hi - lo)


def _cache_key(base_rgb: RGB, kind: str, params: str) -> str:
    digest = hashlib.sha256(base_rgb.tobytes())
    digest.update(kind.encode("utf-8"))
    digest.update(params.encode("utf-8"))
    return digest.hexdigest()[:16]


class DerivedMapCache:
    """Caches maps to ``mockup-templates/{name}/_derived/``, keyed by
    ``hash(source image bytes + map params)`` -- a template edit invalidates
    the cache without a manual clear, since the hash changes with the bytes.
    """

    def __init__(self, derived_dir: Path) -> None:
        self._dir = derived_dir

    def luminance(self, colour: str, base_rgb: RGB) -> FloatMap:
        return self._get_or_compute(colour, "luminance", "", base_rgb, luminance_map)

    def height(self, colour: str, base_rgb: RGB, blur_ksize: int = 15) -> FloatMap:
        return self._get_or_compute(
            colour, "height", str(blur_ksize), base_rgb, lambda b: height_map(b, blur_ksize)
        )

    def _get_or_compute(
        self,
        colour: str,
        kind: str,
        params: str,
        base_rgb: RGB,
        compute: Callable[[RGB], FloatMap],
    ) -> FloatMap:
        key = _cache_key(base_rgb, kind, params)
        path = self._dir / f"{colour}-{kind}-{key}.npy"
        if path.is_file():
            loaded: FloatMap = np.load(path)
            return loaded
        result = compute(base_rgb)
        self._dir.mkdir(parents=True, exist_ok=True)
        np.save(path, result)
        return result
