"""In-process caches for the calibrator's preview loop, and the downscale the
editor renders at.

The calibrator re-renders the same photo several times a second, so
:class:`PreviewImages` memoises decoded images and derived maps by path and file
version and hands them out read-only."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar, cast

import numpy as np
from PIL import Image

from etsy_listings.core.application.mockup_templates import LazyMaps, PreviewScene
from etsy_listings.core.application.preparation.previews import EDITOR_ARTWORK_EDGE
from etsy_listings.core.application.scene_previews import EditorCanvas
from etsy_listings.core.bounded_cache import BoundedCache
from etsy_listings.core.render import prepare_material_artwork
from etsy_listings.core.render.io import DesignValidationError, load_design
from etsy_listings.core.render.maps import DerivedMapCache
from etsy_listings.core.render.types import RGB, RGBA, FloatMap
from etsy_listings.core.workspace.file_version import file_version

LIVE_ARTWORK_EDGE = 1024
"""Longest edge of the artwork Position mode draws in the browser. A print
fills about a third of a stage under 1000 screen pixels, so this stays sharp on
a HiDPI screen; the source can be a hundred megapixels."""

EDITOR_MAX_EDGE = 900
"""Longest edge, in px, that the editor's canvas renders at.

A single fixed number rather than "however wide the pane happens to be": the
derived height/luminance maps are cached on disk under a hash of the base
image's bytes, so an arbitrary per-request size would leave one ``.npy`` pair
per window width sitting in every template's ``_renderer/derived/``. Two sizes exist --
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


def _nbytes(value: np.ndarray[Any, Any]) -> int:
    return int(value.nbytes)


def _stamp(path: Path) -> tuple[int | str, ...]:
    """Completed-write token, or a sentinel for a file that has gone."""
    try:
        return file_version(path)
    except OSError:
        return (-1,)


class PreviewImages:
    def __init__(self, budget_bytes: int = CACHE_BUDGET_BYTES) -> None:
        self._cache: BoundedCache[object, np.ndarray[Any, Any]] = BoundedCache(
            budget_bytes, size=_nbytes
        )

    def _get(self, key: object, compute: Callable[[], _Array]) -> _Array:
        def frozen() -> _Array:
            value = compute()
            value.flags.writeable = False
            return value

        return cast("_Array", self._cache.get_or_compute(key, frozen))

    def base(self, path: Path, max_edge: int | None = None) -> ScaledBase:
        """The mockup photo to composite over, downscaled (never upscaled) to
        ``max_edge``."""
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

        image = self._get(("base", str(path), stamp, target), decode)
        return ScaledBase(
            image=image,
            size=true_size,
            scale=image.shape[1] / true_size[0],
            token=f"{path}|{stamp}|{target[0]}x{target[1]}",
        )

    def design(self, path: Path, max_edge: int | None = None) -> RGBA:
        """Full artwork, or with ``max_edge`` an approximate editor-only size
        (the Marigold editor caps it before building float mips)."""

        def decode() -> RGBA:
            if max_edge is None:
                return load_design(path)
            if max_edge < 1:
                raise ValueError("Editor artwork size must be positive")
            with Image.open(path) as image:
                if image.mode != "RGBA":
                    raise DesignValidationError("Design must have an alpha channel (RGBA)")
                image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
                array: RGBA = np.array(image, dtype=np.uint8)
                return array

        return self._get(("design", str(path), _stamp(path), max_edge), decode)

    def material_design(self, path: Path, max_edge: int) -> tuple[RGBA, FloatMap]:
        """Retain exact linear artwork samples under the same total byte budget."""
        for _ in range(3):
            # Stamp before decoding, or a replacement caches old samples under its new version.
            stamp = _stamp(path)
            design = self.design(path, max_edge=max_edge)
            if _stamp(path) == stamp:
                break
        else:
            raise OSError("Artwork changed repeatedly while reading preview samples; retry")
        packed = self._get(
            ("material-design", str(path), stamp, max_edge),
            lambda: prepare_material_artwork(design),
        )
        return design, packed

    def photo(self, path: Path) -> RGB:
        return self.base(path).image

    def canvas(self, scene: PreviewScene) -> EditorCanvas:
        base = self.base(scene.photo.path, EDITOR_MAX_EDGE)
        directory, key = scene.derived_dir, scene.photo.map_key
        return EditorCanvas(
            base.image,
            base.scale,
            LazyMaps(
                height=lambda: self.height(directory, key, base),
                luminance=lambda: self.luminance(directory, key, base),
            ),
        )

    def artwork(self, path: Path) -> tuple[RGBA, FloatMap]:
        return self.material_design(path, EDITOR_ARTWORK_EDGE)

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
        """A derived map, memoised in front of the on-disk ``DerivedMapCache``,
        whose hits still hash every pixel and load a photo-sized float map."""
        return self._get(("map", kind, map_key, base.token), compute)

    @property
    def held_bytes(self) -> int:
        return self._cache.held

    def clear(self) -> None:
        self._cache.clear()


PREVIEW_IMAGES = PreviewImages()
"""The app's shared memo. Process-wide on purpose: ``etsy-listings ui`` is one
uvicorn process serving one user, and the whole point is that the second
request for a photo does not re-read it."""
