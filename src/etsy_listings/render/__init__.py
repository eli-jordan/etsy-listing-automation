"""Turning a design and a blank mockup photo into a composite. A7.

Pure: ndarrays and frozen config in, an image out. No I/O outside
:mod:`~etsy_listings.render.io` and :class:`DerivedMapCache`, no globals, no
clock -- which is what makes both the lockfile's input hash and the golden
suite meaningful. Nothing here knows a workspace, a listing or a Printify
product exists; callers own opening files and handing over arrays.

``template.yaml``'s models live here too, rather than in ``config``: that file
is render geometry and render settings from top to bottom. ``Workspace`` is
what reads and writes it (``load_template_config`` here only parses data
already in hand).
"""

from etsy_listings.render.config import (
    AnyTemplate,
    BoundingBox,
    ColourMatrixTemplate,
    DisplaceConfig,
    MultipleTemplate,
    Placement,
    Point,
    RenderConfig,
    ShadeConfig,
    SingleTemplate,
    TemplateConfig,
    dump_template_config,
    load_template_config,
)
from etsy_listings.render.io import (
    DesignValidationError,
    encode_png,
    load_design,
    load_template_base,
    save_png,
)
from etsy_listings.render.maps import DerivedMapCache, height_map, luminance_map
from etsy_listings.render.pipeline import Layer, render_scene
from etsy_listings.render.swatch import sample_swatch
from etsy_listings.render.types import RGB, RGBA, FloatMap

__all__ = [
    # The array vocabulary every function here speaks.
    "RGB",
    "RGBA",
    "FloatMap",
    # Render configuration, and the three shapes a template.yaml can take.
    "AnyTemplate",
    "BoundingBox",
    "ColourMatrixTemplate",
    "DisplaceConfig",
    "MultipleTemplate",
    "Placement",
    "Point",
    "RenderConfig",
    "ShadeConfig",
    "SingleTemplate",
    "TemplateConfig",
    "dump_template_config",
    "load_template_config",
    # Compositing. One function for all three kinds -- see pipeline.py.
    "Layer",
    "render_scene",
    # Derived maps, and their on-disk cache.
    "DerivedMapCache",
    "height_map",
    "luminance_map",
    # The I/O boundary, kept out of the passes so those stay pure.
    "DesignValidationError",
    "encode_png",
    "load_design",
    "load_template_base",
    "save_png",
    "sample_swatch",
]
"""The individual passes (``warp``/``displace``/``shade``/``export``) are
deliberately absent: they are the *inside* of ``render_scene``, goldened
per-pass so a pixel change can be attributed, and composing them in some other
order elsewhere is exactly what A7 exists to prevent. Import
``render.passes`` directly if you are testing one."""
