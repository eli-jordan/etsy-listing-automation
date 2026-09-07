"""In-process caches for the calibrator's preview loop, and the downscale the
editor renders at.

The render *stage* reads each image once per run, so it has never needed a
cache and does not get one -- :mod:`etsy_listings.render.io` stays the plain
I/O boundary it is documented as. The calibrator is the opposite shape: it
re-renders the same photo, against the same test design, several times a
second while a box is being dragged. Without this, every one of those frames
re-decoded a multi-megapixel mockup PNG *and* a multi-megapixel design PNG
from disk and re-derived the height/luminance maps -- work that dominated the
render itself and is identical every time.

Two things live here because they answer the same question ("what does this
preview need in memory?"):

* :class:`PreviewImages` -- the memo. Keyed on path *and* mtime, so editing a
  photo or replacing a test design invalidates it with no manual clear, the
  same rule ``DerivedMapCache`` uses on disk.
* :class:`ScaledBase` -- the downscale. The editor renders at
  :data:`EDITOR_MAX_EDGE` rather than the photo's true size, which is what
  makes dragging feel live; ``scale`` is what the caller multiplies bounding
  boxes by to get from the template's true pixel space (which is what
  ``template.yaml`` stores, and what the editor's overlay works in) into the
  smaller canvas actually being rendered.

Cached arrays are handed out **read-only**. Every render pass is pure (A7), so
nothing should ever want to write to one; the flag makes a future accident a
loud ``ValueError`` here rather than a preview that is subtly wrong for
whoever asks next.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import numpy as np
from PIL import Image

from etsy_listings.render.io import load_design
from etsy_listings.render.maps import DerivedMapCache
from etsy_listings.render.types import RGB, RGBA, FloatMap

EDITOR_MAX_EDGE = 900
"""Longest edge, in px, that the editor's canvas renders at.

A single fixed number rather than "however wide the pane happens to be": the
derived height/luminance maps are cached on disk under a hash of the base
image's bytes, so an arbitrary per-request size would leave one ``.npy`` pair
per window width sitting in every template's ``_derived/``. Two sizes exist --
this one and full -- so at most two pairs do.

900 is comfortably above the ~700px the canvas occupies on a 1280px window at
1x, so the editor is not looking at an upscale, and far below the 3000-5000px
a real garment photo runs to.
"""

CACHE_BUDGET_BYTES = 384 * 1024 * 1024
"""How much decoded imagery the preview loop may hold. Budgeted in bytes
rather than entries because the entries differ by two orders of magnitude: a
900px editor base is ~2MB, a 4500x5400 RGBA design is ~97MB, and an
entry-counted cache sized for one is either useless or ruinous for the other.
"""

_Array = TypeVar("_Array", bound="np.ndarray[Any, Any]")


@dataclass(frozen=True)
class ScaledBase:
    """A mockup photo decoded for a preview, possibly downscaled."""

    image: RGB
    """What to render onto -- at ``scale``, not necessarily the true size."""

    size: tuple[int, int]
    """The photo's **true** ``(width, height)``. This is the coordinate space
    ``template.yaml`` stores boxes in, so it is what the client's overlay must
    use as its viewBox regardless of how big the image it draws over is."""

    scale: float
    """Rendered px per true px, in ``(0, 1]``. Multiply a bounding box by this
    to place it on ``image``; 1.0 when no downscale applied."""

    token: str
    """Identity of this exact array (path, mtime and rendered size), for
    keying anything derived from it."""


class _ArrayCache:
    """A least-recently-used cache bounded by the total ``nbytes`` it holds.

    Deliberately not ``functools.lru_cache``: that counts entries, and one
    full-size design array is worth fifty editor-scale bases.

    Locked, because FastAPI runs ``def`` endpoints on a thread pool and two
    previews can therefore be in flight at once. The lock is held for the
    bookkeeping only, never across ``compute()`` -- decoding a 20-megapixel
    PNG under a mutex would serialise exactly the requests this exists to make
    cheap. Two threads may therefore decode the same image once each; the
    loser's copy is dropped, so every caller still gets the *same* array back
    and the byte accounting counts it once.
    """

    def __init__(self, budget_bytes: int) -> None:
        self._budget = budget_bytes
        self._entries: OrderedDict[object, np.ndarray[Any, Any]] = OrderedDict()
        self._held = 0
        self._lock = threading.Lock()

    def get(self, key: object, compute: Callable[[], _Array]) -> _Array:
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                self._entries.move_to_end(key)
                return cached  # type: ignore[return-value]

        value = compute()
        value.flags.writeable = False

        with self._lock:
            raced = self._entries.get(key)
            if raced is not None:
                self._entries.move_to_end(key)
                return raced  # type: ignore[return-value]
            # An array bigger than the whole budget is served without being
            # stored -- caching it would evict everything and then itself.
            if value.nbytes <= self._budget:
                self._entries[key] = value
                self._held += value.nbytes
                while self._held > self._budget:
                    _, evicted = self._entries.popitem(last=False)
                    self._held -= evicted.nbytes
        return value

    @property
    def held_bytes(self) -> int:
        with self._lock:
            return self._held

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._held = 0


def _stamp(path: Path) -> int:
    """Mtime in ns, or -1 for a file that has gone. Part of every cache key:
    a re-exported photo or a replaced test design must not be served from a
    memo of the old bytes."""
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return -1


class PreviewImages:
    """Everything the preview endpoint has to load, memoised across requests.

    One instance is shared by the app (:data:`PREVIEW_IMAGES`); tests build
    their own so the memo cannot leak between them.
    """

    def __init__(self, budget_bytes: int = CACHE_BUDGET_BYTES) -> None:
        self._cache = _ArrayCache(budget_bytes)

    def base(self, path: Path, max_edge: int | None = None) -> ScaledBase:
        """The mockup photo to composite over, downscaled to ``max_edge`` if
        it is larger than that.

        Never upscales: a small template photo previews at its own size, so a
        fixture set or a low-resolution mockup is not blurred into looking
        worse than it is, and ``scale`` stays exactly 1.0 for it.
        """
        stamp = _stamp(path)
        with Image.open(path) as probe:
            true_size = probe.size
        longest = max(true_size)
        ratio = 1.0 if max_edge is None or longest <= max_edge else max_edge / longest
        target = (max(1, round(true_size[0] * ratio)), max(1, round(true_size[1] * ratio)))

        def decode() -> RGB:
            with Image.open(path) as image:
                rgb = image.convert("RGB")
                if target != true_size:
                    rgb = rgb.resize(target, Image.Resampling.LANCZOS)
                array: RGB = np.array(rgb, dtype=np.uint8)
            return array

        image = self._cache.get(("base", str(path), stamp, target), decode)
        return ScaledBase(
            image=image,
            size=true_size,
            # Recomputed from the array rather than reusing `ratio`: rounding
            # to whole pixels moves it, and a box scaled by the *requested*
            # factor would sit fractionally off the canvas it lands on.
            scale=image.shape[1] / true_size[0],
            token=f"{path}|{stamp}|{target[0]}x{target[1]}",
        )

    def design(self, path: Path) -> RGBA:
        """The test design, at full size.

        Not downscaled along with the base: ``warp`` costs one sample per
        *destination* pixel, so a smaller canvas already pays for itself, and
        resampling the source as well would make the editor's preview differ
        from the render for a reason nothing on screen explains.
        """
        return self._cache.get(("design", str(path), _stamp(path)), lambda: load_design(path))

    def height(self, derived_dir: Path, map_key: str, base: ScaledBase) -> FloatMap:
        cache = DerivedMapCache(derived_dir)
        return self._map("height", map_key, base, lambda: cache.height(map_key, base.image))

    def luminance(self, derived_dir: Path, map_key: str, base: ScaledBase) -> FloatMap:
        cache = DerivedMapCache(derived_dir)
        return self._map("luminance", map_key, base, lambda: cache.luminance(map_key, base.image))

    def _map(
        self,
        kind: str,
        map_key: str,
        base: ScaledBase,
        compute: Callable[[], FloatMap],
    ) -> FloatMap:
        """A derived map, through the same on-disk ``DerivedMapCache`` the
        render stage uses -- this only adds a memo in front of it.

        Worth having on top of the disk cache: that one is keyed by a SHA-256
        over the whole base array, so a *hit* still costs a hash of every
        pixel plus an ``np.load`` of a float32 map the same size as the photo.
        Once per drag that is invisible; five times a second it is not.
        """
        return self._cache.get(("map", kind, map_key, base.token), compute)

    @property
    def held_bytes(self) -> int:
        return self._cache.held_bytes

    def clear(self) -> None:
        self._cache.clear()


PREVIEW_IMAGES = PreviewImages()
"""The app's shared memo. Process-wide on purpose: ``etsy-listings ui`` is one
uvicorn process serving one user, and the whole point is that the second
request for a photo does not re-read it."""
