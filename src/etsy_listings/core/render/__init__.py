"""Turning a design and a blank mockup photo into a composite. ADR-0012.

Pure: ndarrays and frozen config in, an image out. No I/O outside
:mod:`~etsy_listings.core.render.io` and :class:`DerivedMapCache`, no globals, no
clock -- which is what makes both the lockfile's input hash and the golden
suite meaningful. Nothing here knows a workspace, a listing or a Printify
product exists; callers own opening files and handing over arrays.

``template.yaml``'s models live here too, rather than in ``config``: that file
is render geometry and render settings from top to bottom. ``workspace.template_state``
reads it and ``CalibrationStore`` writes it (``load_template_config`` here only parses data
already in hand).

``positions`` (ADR-0058) is not re-exported: import it directly. Its
``PositionLimits``/``ScaleLimits`` are structural protocols, so
``config.settings.TemplatePositionLimits`` satisfies them without making render
depend on settings.
"""

from etsy_listings.core.render.config import (
    AnyRenderer,
    AnyTemplate,
    BoundingBox,
    ColourMatrixTemplate,
    DisplaceConfig,
    LayerBoxes,
    MarigoldAppearance,
    MarigoldConfig,
    MarigoldInference,
    MarigoldRenderer,
    MultipleTemplate,
    PhotoWarpConfig,
    PhotoWarpRenderer,
    Placement,
    PlacementId,
    Point,
    PreparationRequiredError,
    RenderConfig,
    Renderer,
    ShadeConfig,
    SingleTemplate,
    TemplateConfig,
    dump_template_config,
    load_template_config,
    scene_colours,
    scene_layers,
)
from etsy_listings.core.render.io import (
    DesignValidationError,
    encode_png,
    load_design,
    load_template_base,
    save_png,
)
from etsy_listings.core.render.maps import DerivedMapCache, height_map, luminance_map
from etsy_listings.core.render.material import (
    MaterialLayer,
    MaterialMaps,
    prepare_material_artwork,
    render_marigold_scene,
)
from etsy_listings.core.render.pipeline import Layer, render_scene
from etsy_listings.core.render.swatch import sample_swatch
from etsy_listings.core.render.types import RGB, RGBA, FloatMap

__all__ = [
    "RGB",
    "RGBA",
    "AnyRenderer",
    "AnyTemplate",
    "BoundingBox",
    "ColourMatrixTemplate",
    "DerivedMapCache",
    "DesignValidationError",
    "DisplaceConfig",
    "FloatMap",
    "Layer",
    "LayerBoxes",
    "MarigoldAppearance",
    "MarigoldConfig",
    "MarigoldInference",
    "MarigoldRenderer",
    "MaterialLayer",
    "MaterialMaps",
    "MultipleTemplate",
    "PhotoWarpConfig",
    "PhotoWarpRenderer",
    "Placement",
    "PlacementId",
    "Point",
    "PreparationRequiredError",
    "RenderConfig",
    "Renderer",
    "ShadeConfig",
    "SingleTemplate",
    "TemplateConfig",
    "dump_template_config",
    "encode_png",
    "height_map",
    "load_design",
    "load_template_base",
    "load_template_config",
    "luminance_map",
    "prepare_material_artwork",
    "render_marigold_scene",
    "render_scene",
    "sample_swatch",
    "save_png",
    "scene_colours",
    "scene_layers",
]
"""MaterialMaps carries an explicit photo origin and optional reference size for
compact preparation maps. The pure renderer returns the complete reference photo.

The public identity module provides decoded artwork and prepared scene
identities for CPU preview promotion; it imports no orchestration code.

The individual passes (``warp``/``displace``/``shade``/``export_many``) are
deliberately absent: they are the *inside* of ``render_scene``, goldened
per-pass so a pixel change can be attributed, and composing them in some other
order elsewhere is exactly what ADR-0012 exists to prevent. Import
``render.passes`` directly if you are testing one."""
