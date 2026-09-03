"""``render()``: warp -> displace -> shade -> export, composed in fixed order.

Pure, per A7 -- callers (the render stage, the calibrator's preview endpoint)
own loading the design/template arrays and the derived maps; this function
never touches a filesystem.
"""

from __future__ import annotations

from PIL import Image

from etsy_listings.render.config import RenderConfig
from etsy_listings.render.passes import displace, export, shade, warp
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
    layer = warp(design, cfg.warp, (w, h))

    if cfg.displace.enabled:
        if height is None:
            raise ValueError("displace is enabled but no height map was provided")
        layer = displace(layer, cfg.displace, height)

    if cfg.shade.enabled:
        if luminance is None:
            raise ValueError("shade is enabled but no luminance map was provided")
        layer = shade(layer, cfg.shade, luminance)

    return export(template_base, layer)
