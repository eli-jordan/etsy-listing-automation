"""``render_scene()``: warp, displace and shade per layer in fixed order, folded
over one base; the one Photo warp compositor for all three template kinds."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PIL import Image

from etsy_listings.core.render.config import RenderConfig
from etsy_listings.core.render.passes import displace, export_many, print_bounds, shade, warp
from etsy_listings.core.render.types import RGB, RGBA, FloatMap


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
        result = _displaced(result, entry.cfg, height)
        result = _shaded(result, entry.cfg, luminance)
        warped_layers.append(result)

    return export_many(template_base, warped_layers)


def _displaced(layer: RGBA, cfg: RenderConfig, height: FloatMap | None) -> RGBA:
    if not cfg.displace.enabled:
        return layer
    if height is None:
        raise ValueError("displace is enabled but no height map was provided")
    return displace(layer, cfg.displace, height)


def _shaded(layer: RGBA, cfg: RenderConfig, luminance: FloatMap | None) -> RGBA:
    if not cfg.shade.enabled:
        return layer
    if luminance is None:
        raise ValueError("shade is enabled but no luminance map was provided")
    # Outside the print, alpha is zero and export_many takes none of the layer's colour,
    # so shading only the print region changes no output pixel.
    region = print_bounds(layer)
    if region is None:
        return layer
    shaded = layer.copy()
    shaded[region] = shade(layer[region], cfg.shade, luminance[region])
    return shaded
