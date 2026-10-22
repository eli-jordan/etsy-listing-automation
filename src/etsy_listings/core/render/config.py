"""Frozen render configuration. ADR-0012: canonical JSON of ``RenderConfig`` is what
gets hashed into the lockfile's render stage entry, so every field here must be
something that can differ between two "the same design" runs -- no derived
values, no file paths (those are workspace-relative strings elsewhere, hashed
separately as part of the render stage's desired state).

A template is exactly one of three kinds -- never a mix (multi-placement
redesign, see docs/features/multi-placement-rendering-20260903/spec.md):

- ``colour-matrix`` -- one photo per colour, the design at the same
  ``bounding_box`` in every one. No per-colour override: a colour whose photo
  is actually framed differently is a ``single``-kind template instead.
- ``multiple`` -- several garments in one photo, each a ``Placement`` with its
  own ``bounding_box``. This is the one place per-item geometry exists, since
  that is the entire point of a chart.
- ``single`` -- one photo, one garment.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, TypeAdapter, model_validator


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
    """Implemented but off by default -- over-strong displacement looks
    melted, so it's tuned per template in the calibrator's live preview."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = False
    strength: float = 0.0  # 0..1, calibrated per template


class ShadeConfig(BaseModel):
    """Blends the base mockup photo's own greyscale lighting over the printed
    design, so a flat design picks up the garment's real fold shadows and
    light falloff instead of looking pasted on as a flat rectangle -- this is
    why a plain flat-lay PNG is enough to mock up, with no purchased
    Photoshop lighting map needed. On by default: almost every mockup needs
    it. ``multiply`` crushes prints on dark garments, so ``soft-light`` or a
    mid-grey pivot is used for those instead."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = True
    opacity: float = 0.6  # 0..1
    blend: Literal["multiply", "soft-light", "grey-pivot"] = "soft-light"


class RenderConfig(BaseModel):
    """The resolved, per-layer configuration a single render call consumes.
    Frozen and hashable via :meth:`canonical_json`."""

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
    lighting_strength: float = Field(default=1.0, ge=0, le=1, allow_inf_nan=False)
    fabric_texture: float = Field(default=0.25, ge=0, le=1, allow_inf_nan=False)
    print_shine: float = Field(default=0.0, ge=0, le=1, allow_inf_nan=False)


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


class PreparationRequired(ValueError):
    """ADR-0054 forbids rendering Marigold through Photo warp."""


def photo_warp_config(renderer: AnyRenderer, box: BoundingBox) -> RenderConfig:
    if not isinstance(renderer, PhotoWarpRenderer):
        raise PreparationRequired("Prepare the template first: Marigold maps are required")
    return RenderConfig(bounding_box=box, **renderer.config.model_dump())


def _safe_id(value: str) -> str:
    # ADR-0054: an ID owns durable assets and survives reorder/recolour.
    reserved = {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value) or value.casefold() in reserved:
        raise ValueError("placement id must be a non-empty safe path segment")
    return value


PlacementId = Annotated[str, AfterValidator(_safe_id)]


class ColourMatrixTemplate(BaseModel):
    """One photo per colour, same design position in all of them. Scene
    images are ``{colour-slug}.png`` per colour -- there is no
    ``colours:`` list in the YAML, since the filenames present in the
    directory *are* the colour set."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["colour-matrix"] = "colour-matrix"
    bounding_box: BoundingBox
    renderer: Renderer

    def render_config(self) -> RenderConfig:
        return photo_warp_config(self.renderer, self.bounding_box)


def _reject_template_artwork(value: Any) -> Any:  # noqa: ANN401 - pydantic validator boundary
    """A template no longer chooses artwork (ADR-0053): a colour resolves to the
    same file in every mockup scene and on Printify, and a mockup showing a
    different print from the delivered shirt is not a useful exception. The
    field is refused by name rather than dropped, since ignoring it would
    render something other than what the file asks for.

    ``artwork: null`` is not an override, and is what the calibrator wrote
    into every ``multiple`` and ``single`` template before ADR-0053 -- so it loads,
    and the next save drops it."""
    if isinstance(value, Mapping) and value.get("artwork") is not None:
        raise ValueError(
            "artwork: is no longer a template setting (ADR-0053) -- remove it; the "
            "listing's design: decides which file each colour prints"
        )
    if isinstance(value, Mapping) and "artwork" in value:
        # Dropped here: these models forbid unknown keys (ADR-0054).
        return {k: v for k, v in value.items() if k != "artwork"}
    return value


class Placement(BaseModel):
    """One garment within a ``multiple``-kind scene."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: PlacementId
    colour: str
    bounding_box: BoundingBox

    @model_validator(mode="before")
    @classmethod
    def _no_artwork(cls, value: Any) -> Any:  # noqa: ANN401 - pydantic validator boundary
        return _reject_template_artwork(value)


class MultipleTemplate(BaseModel):
    """Several garments in one photo. ``displace``/``shade`` are scene-level
    only -- one photo, one lighting pass; a placement needing different
    rendering treatment belongs in its own template instead."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["multiple"] = "multiple"
    placements: list[Placement]
    colour_coverage: Literal["exact", "subset"] = "exact"
    """Governs a mismatch between this photo's placement colours and a
    listing's ``colors:``. ``exact`` (default): they must match exactly, or
    ``plan`` fails naming the mismatch -- use when a chart is meant to
    represent precisely what one listing sells. ``subset``: placements for
    colours the listing doesn't sell are skipped and ``plan`` reports which --
    use for one shop-wide chart reused across listings selling different
    subsets of the garment's colour range."""
    renderer: Renderer

    @model_validator(mode="after")
    def unique_ids(self) -> MultipleTemplate:
        ids = [placement.id.casefold() for placement in self.placements]
        if len(ids) != len(set(ids)):
            raise ValueError("placement IDs must be unique")
        return self

    def render_config_for(self, placement: Placement) -> RenderConfig:
        return photo_warp_config(self.renderer, placement.bounding_box)


class SingleTemplate(BaseModel):
    """One photo, one garment -- a lifestyle shot, a folded product photo,
    anything that isn't part of a colour set."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["single"] = "single"
    colour: str | None = None
    """Which garment colour this photo depicts -- what a light/dark listing
    resolves its artwork by (ADR-0053). There's only one photo, so nothing needs it
    to disambiguate a filename; without it, the scene prints ``default`` and
    cannot be used by a listing with light and dark designs."""
    bounding_box: BoundingBox
    renderer: Renderer

    @model_validator(mode="before")
    @classmethod
    def _no_artwork(cls, value: Any) -> Any:  # noqa: ANN401 - pydantic validator boundary
        return _reject_template_artwork(value)

    def render_config(self) -> RenderConfig:
        return photo_warp_config(self.renderer, self.bounding_box)


AnyTemplate = ColourMatrixTemplate | MultipleTemplate | SingleTemplate
"""One loaded ``template.yaml``, whichever kind it turned out to be.

The plain union, for annotating variables and return types. Use
:data:`TemplateConfig` -- the same union carrying pydantic's discriminator --
wherever pydantic itself does the dispatch (a FastAPI ``response_model``, a
request body, a ``TypeAdapter``)."""


def scene_layers(
    template: AnyTemplate, colour: str | None
) -> list[tuple[str | None, RenderConfig]]:
    """``(depicted colour, render config)`` per layer of one scene, in paint
    order -- the colour each layer's artwork resolves by (A35, PRD 30).

    A ``colour-matrix`` scene depicts the colour it is rendered for, a
    ``single`` scene its own ``colour`` (``None`` when it names none), and a
    ``multiple`` scene one colour per placement. Here, beside the three
    shapes, because the render stage and the editor's scene preview both need
    it and a second copy is how the two would come to show different files.
    """
    if isinstance(template, ColourMatrixTemplate):
        # Same geometry in every colour's photo: a colour framed differently
        # is a `single`-kind template instead, never a per-colour override.
        return [(colour, template.render_config())]
    if isinstance(template, SingleTemplate):
        return [(template.colour, template.render_config())]
    return [(p.colour, template.render_config_for(p)) for p in template.placements]


def scene_colours(template: AnyTemplate, colour: str | None) -> list[tuple[str | None, str | None]]:
    """``(depicted colour, placement ID)`` per layer of one scene, in
    :func:`scene_layers`'s order, for any renderer: a prepared scene pairs
    each layer's artwork with its placement's accepted maps rather than a
    Photo warp configuration (ADR-0054)."""
    if isinstance(template, MultipleTemplate):
        return [(p.colour, p.id) for p in template.placements]
    return [(colour if isinstance(template, ColourMatrixTemplate) else template.colour, None)]


TemplateConfig = Annotated[AnyTemplate, Field(discriminator="kind")]
"""``mockup-templates/{name}/template.yaml``, written by the calibrator. A
discriminated union, not a wrapping model -- the file *is* one of the three
shapes. Parse with :func:`load_template_config`; read one off disk with
``Workspace.load_template_config``, which is the only thing that knows where
the file lives."""

_TEMPLATE_CONFIG_ADAPTER: TypeAdapter[AnyTemplate] = TypeAdapter(TemplateConfig)


def load_template_config(data: object) -> AnyTemplate:
    """Parse already-read YAML/JSON data. The file-level read lives on
    ``Workspace`` -- this half stays pure, so ``render`` still knows nothing
    about where a workspace keeps its templates."""
    return _TEMPLATE_CONFIG_ADAPTER.validate_python(data)


def dump_template_config(config: AnyTemplate) -> dict[str, object]:
    result: dict[str, object] = _TEMPLATE_CONFIG_ADAPTER.dump_python(config, mode="json")
    return result
