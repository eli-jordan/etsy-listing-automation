from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from etsy_listings.core.errors import ConflictError

UnitInterval = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class Point(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)


def _validate_non_degenerate(
    box: tuple[Point, Point, Point, Point],
) -> tuple[Point, Point, Point, Point]:
    xs = [p.x for p in box]
    ys = [p.y for p in box]
    if max(xs) - min(xs) < 1 or max(ys) - min(ys) < 1:
        raise ValueError("bounding_box is degenerate (zero width or height)")
    return box


BoundingBox = Annotated[tuple[Point, Point, Point, Point], AfterValidator(_validate_non_degenerate)]
"""Four corners of the print area on the template image, in pixel space,
ordered top-left, top-right, bottom-right, bottom-left (homography to a
quad, not x/y/w/h, so angled and draped photos are representable)."""


class DisplaceConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = False
    strength: UnitInterval = 0.0


class ShadeConfig(BaseModel):
    """Blends the base mockup photo's own greyscale lighting over the printed
    design. On by default: almost every mockup needs it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = True
    opacity: UnitInterval = 0.6
    blend: Literal["multiply", "soft-light", "grey-pivot"] = "soft-light"


class RenderConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    bounding_box: BoundingBox
    displace: DisplaceConfig = DisplaceConfig()
    shade: ShadeConfig = ShadeConfig()

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


class PhotoWarpConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    displace: DisplaceConfig = DisplaceConfig()
    shade: ShadeConfig = ShadeConfig()


class MarigoldInference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    num_inference_steps: int = Field(default=10, gt=0, strict=True)
    ensemble_size: int = Field(default=3, gt=0, strict=True)


class MarigoldAppearance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    lighting_source: Literal["estimated", "photo"] = "estimated"
    lighting_strength: UnitInterval = 1.0
    fabric_texture: UnitInterval = 0.25
    print_shine: UnitInterval = 0.0


class MarigoldConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    inference: MarigoldInference = MarigoldInference()
    appearance: MarigoldAppearance = MarigoldAppearance()


class PhotoWarpRenderer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["photo-warp"]
    config: PhotoWarpConfig = PhotoWarpConfig()


class MarigoldRenderer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["marigold"]
    config: MarigoldConfig = MarigoldConfig()


AnyRenderer = PhotoWarpRenderer | MarigoldRenderer
Renderer = Annotated[AnyRenderer, Field(discriminator="type")]


class PreparationRequiredError(ConflictError, ValueError):
    """ADR-0054 forbids rendering Marigold through Photo warp."""


def photo_warp_config(renderer: AnyRenderer, box: BoundingBox) -> RenderConfig:
    if not isinstance(renderer, PhotoWarpRenderer):
        raise PreparationRequiredError("Prepare the template first: Marigold maps are required")
    return RenderConfig(bounding_box=box, **renderer.config.model_dump())


_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
)


def _path_segment_id(value: str) -> str:
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value)
        or value.casefold() in _WINDOWS_RESERVED_NAMES
    ):
        raise ValueError("placement id must be a non-empty safe path segment")
    return value


PlacementId = Annotated[str, AfterValidator(_path_segment_id)]


class ColourMatrixTemplate(BaseModel):
    """One photo per colour, named by colour slug, with the design in the same position."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["colour-matrix"] = "colour-matrix"
    bounding_box: BoundingBox
    renderer: Renderer
    labels: list[str] = []

    def render_config(self) -> RenderConfig:
        return photo_warp_config(self.renderer, self.bounding_box)


class Placement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: PlacementId
    colour: str
    bounding_box: BoundingBox


class MultipleTemplate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)

    kind: Literal["multiple"] = "multiple"
    placements: list[Placement]
    colour_coverage: Literal["exact", "subset"] = "exact"
    """How a mismatch between this photo's placement colours and a listing's
    ``colors:`` is handled. ``exact``: ``plan`` fails naming the mismatch.
    ``subset``: placements for colours the listing doesn't sell are skipped
    and ``plan`` reports which, for one chart shared across listings."""
    renderer: Renderer
    labels: list[str] = []

    @model_validator(mode="after")
    def unique_ids(self) -> MultipleTemplate:
        ids = [placement.id.casefold() for placement in self.placements]
        if len(ids) != len(set(ids)):
            raise ValueError("placement IDs must be unique")
        return self

    def render_config_for(self, placement: Placement) -> RenderConfig:
        return photo_warp_config(self.renderer, placement.bounding_box)


class SingleTemplate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)

    kind: Literal["single"] = "single"
    colour: str | None = None
    """Which garment colour this photo depicts, which a light/dark listing
    resolves its artwork by. Without it the scene prints ``default`` and a
    listing with light and dark designs cannot use it."""
    bounding_box: BoundingBox
    renderer: Renderer
    labels: list[str] = []

    def render_config(self) -> RenderConfig:
        return photo_warp_config(self.renderer, self.bounding_box)


AnyTemplate = ColourMatrixTemplate | MultipleTemplate | SingleTemplate
"""One loaded ``template.yaml``, whichever kind it turned out to be.

The plain union, for annotating variables and return types. Use
:data:`TemplateConfig` -- the same union carrying pydantic's discriminator --
wherever pydantic itself does the dispatch (a FastAPI ``response_model``, a
request body, a ``TypeAdapter``)."""


LayerBoxes = Mapping[str | None, BoundingBox]
"""A listing's boxes for one template's layers, keyed by placement ID, or by
``None`` for a ``single`` or ``colour-matrix`` template's one layer (ADR-0058).
A layer no key names keeps the template's box."""

_NO_BOXES: LayerBoxes = {}


def scene_layers(
    template: AnyTemplate, colour: str | None, boxes: LayerBoxes = _NO_BOXES
) -> list[tuple[str | None, RenderConfig]]:
    renderer = template.renderer
    return [
        (depicted, photo_warp_config(renderer, box))
        for (depicted, _), box in zip(
            scene_colours(template, colour), scene_boxes(template, boxes), strict=True
        )
    ]


def scene_colours(template: AnyTemplate, colour: str | None) -> list[tuple[str | None, str | None]]:
    if isinstance(template, MultipleTemplate):
        return [(p.colour, p.id) for p in template.placements]
    return [(colour if isinstance(template, ColourMatrixTemplate) else template.colour, None)]


def scene_boxes(template: AnyTemplate, boxes: LayerBoxes = _NO_BOXES) -> list[BoundingBox]:
    if isinstance(template, MultipleTemplate):
        return [boxes.get(p.id, p.bounding_box) for p in template.placements]
    return [boxes.get(None, template.bounding_box)]


TemplateConfig = Annotated[AnyTemplate, Field(discriminator="kind")]
"""``mockup-templates/{name}/template.yaml``, written by the calibrator. A
discriminated union, not a wrapping model -- the file *is* one of the three
shapes. Parse with :func:`load_template_config`; read one off disk with
``workspace.template_state``, the only reader that knows where
the file lives."""

_TEMPLATE_CONFIG_ADAPTER: TypeAdapter[AnyTemplate] = TypeAdapter(TemplateConfig)


def load_template_config(data: object) -> AnyTemplate:
    return _TEMPLATE_CONFIG_ADAPTER.validate_python(data)


def dump_template_config(config: AnyTemplate) -> dict[str, object]:
    result: dict[str, object] = _TEMPLATE_CONFIG_ADAPTER.dump_python(config, mode="json")
    if not config.labels:
        del result["labels"]
    return result
