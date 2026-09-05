"""``render_scene()``: warp -> displace -> shade applied independently per
layer, in fixed order, then folded over one base.

One function for all three template kinds. There used to be a second,
``render()``, for the single-layer case -- but it was the same sequence ending
in :func:`~etsy_listings.render.passes.export` instead of ``export_many``, and
those perform identical arithmetic over one layer (pinned by
``test_export_many_with_one_layer_matches_export``, and by the end-to-end
goldens). Both callers -- the render stage and the calibrator's preview
endpoint -- now go through here, so a colour-matrix scene and a chart cannot
drift apart in how they composite.

Pure, per A7 -- callers own loading the design/template arrays and the derived
maps; these functions never touch a filesystem.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PIL import Image

from etsy_listings.render.config import RenderConfig
from etsy_listings.render.passes import displace, export_many, shade, warp
from etsy_listings.render.types import RGB, RGBA, FloatMap


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
