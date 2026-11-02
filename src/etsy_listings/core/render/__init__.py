"""Turning a design and a blank mockup photo into a composite. ADR-0012.

Pure: ndarrays and frozen config in, an image out. No I/O outside
:mod:`~etsy_listings.core.render.io` and :class:`DerivedMapCache`, no globals, no
clock -- which is what makes both the lockfile's input hash and the golden
suite meaningful. Nothing here knows a workspace, a listing or a Printify
product exists; callers own opening files and handing over arrays.

``template.yaml``'s models live here too, rather than in ``config``: that file
is render geometry and render settings from top to bottom. ``Workspace`` is
what reads and writes it (``load_template_config`` here only parses data
already in hand).

``positions`` exposes ``Pose(scale=1, offset_x=0, offset_y=0, rotation=0)``,
``PoseFit(pose, residual_pixels)``, ``compose(template_box, pose) -> BoundingBox``,
``decompose(template_box, box) -> PoseFit``, ``clamp_pose(pose, limits) -> Pose``
and ``nearest_allowed_pose(template_box, box, limits) -> Pose`` (ADR-0058).
Import these directly from ``positions``. ``PositionLimits``/``ScaleLimits``
are structural protocols; ``config.settings.TemplatePositionLimits`` satisfies
them without making render depend on settings. Offsets are fractions of the box's
rectified W and H; rotation is rigid, in clockwise degrees. Compose the nearest
pose to get repair corners.
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

__all__ = [  # noqa: RUF022 -- grouped by topic, not alphabetically
    # The array vocabulary every function here speaks.
    "RGB",
    "RGBA",
    "FloatMap",
    # Render configuration, and the three shapes a template.yaml can take.
    "AnyRenderer",
    "Renderer",
    "PhotoWarpConfig",
    "PhotoWarpRenderer",
    "MarigoldInference",
    "LayerBoxes",
    "MarigoldAppearance",
    "MarigoldConfig",
    "MarigoldRenderer",
    "PlacementId",
    "PreparationRequiredError",
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
    "scene_colours",
    "scene_layers",
    # Compositing. One function for all three kinds -- see pipeline.py.
    "Layer",
    "render_scene",
    "MaterialMaps",
    "MaterialLayer",
    "prepare_material_artwork",
    "render_marigold_scene",
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
"""MaterialMaps carries an explicit photo origin and optional reference size for
compact preparation maps. The pure renderer returns the complete reference photo.

The public identity module provides decoded artwork and prepared scene
identities for CPU preview promotion; it imports no orchestration code.

The individual passes (``warp``/``displace``/``shade``/``export``) are
deliberately absent: they are the *inside* of ``render_scene``, goldened
per-pass so a pixel change can be attributed, and composing them in some other
order elsewhere is exactly what ADR-0012 exists to prevent. Import
``render.passes`` directly if you are testing one."""
