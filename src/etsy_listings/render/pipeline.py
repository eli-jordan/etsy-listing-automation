"""``render()``: warp -> displace -> shade -> export, composed in fixed order,
for a single design layer. ``render_scene()``: the same sequence applied
independently per layer, then folded over one base -- ``multiple``-kind
scenes only.

Pure, per A7 -- callers (the render stage, the calibrator's preview endpoint)
own loading the design/template arrays and the derived maps; these functions
never touch a filesystem.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PIL import Image

from etsy_listings.render.config import RenderConfig
from etsy_listings.render.passes import displace, export, export_many, shade, warp
from etsy_listings.render.types import RGB, RGBA, FloatMap


def render(
    design: RGBA,
    template_base: RGB,
    cfg: RenderConfig,
    *,
    height: FloatMap | None = None,
    luminance: FloatMap | None = None,
) -> Image.Image:
    h, w = template_base.shape[:2]
    layer = warp(design, cfg.bounding_box, (w, h))

    if cfg.displace.enabled:
        if height is None:
            raise ValueError("displace is enabled but no height map was provided")
        layer = displace(layer, cfg.displace, height)

    if cfg.shade.enabled:
        if luminance is None:
            raise ValueError("shade is enabled but no luminance map was provided")
        layer = shade(layer, cfg.shade, luminance)

    return export(template_base, layer)


@dataclass(frozen=True)
class Layer:
    design: RGBA
    cfg: RenderConfig


def render_scene(
    template_base: RGB,
    layers: Sequence[Layer],
    *,
    height: FloatMap | None = None,
    luminance: FloatMap | None = None,
) -> Image.Image:
    h, w = template_base.shape[:2]
    warped_layers: list[RGBA] = []
    for entry in layers:
        result = warp(entry.design, entry.cfg.bounding_box, (w, h))

        if entry.cfg.displace.enabled:
            if height is None:
                raise ValueError("displace is enabled but no height map was provided")
            result = displace(result, entry.cfg.displace, height)

        if entry.cfg.shade.enabled:
            if luminance is None:
                raise ValueError("shade is enabled but no luminance map was provided")
            result = shade(result, entry.cfg.shade, luminance)

        warped_layers.append(result)

    return export_many(template_base, warped_layers)
