"""Frozen render configuration. A7: canonical JSON of ``RenderConfig`` is what
gets hashed into the lockfile's render stage entry, so every field here must be
something that can differ between two "the same design" runs -- no derived
values, no file paths (those are workspace-relative strings elsewhere, hashed
separately as part of the render stage's desired state).

A template is exactly one of three kinds -- never a mix (multi-placement
redesign, see docs/multi-placement-rendering.md):

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
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, TypeAdapter


class Point(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: float
    y: float


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
ordered top-left, top-right, bottom-right, bottom-left (PRD: homography to a
quad, not x/y/w/h, so angled and draped photos are representable)."""


class DisplaceConfig(BaseModel):
    """PRD: implemented but off by default -- over-strong displacement looks
    melted, so it's tuned per template in the calibrator's live preview."""

    model_config = ConfigDict(frozen=True)

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

    model_config = ConfigDict(frozen=True)

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


class ColourMatrixTemplate(BaseModel):
    """One photo per colour, same design position in all of them. Scene
    images are ``{colour-slug}.png`` per colour (PRD 7a) -- there is no
    ``colours:`` list in the YAML, since the filenames present in the
    directory *are* the colour set."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["colour-matrix"] = "colour-matrix"
    bounding_box: BoundingBox
    displace: DisplaceConfig = DisplaceConfig()
    shade: ShadeConfig = ShadeConfig()

    def render_config(self) -> RenderConfig:
        return RenderConfig(
            bounding_box=self.bounding_box, displace=self.displace, shade=self.shade
        )


class Placement(BaseModel):
    """One garment within a ``multiple``-kind scene."""

    model_config = ConfigDict(frozen=True)

    colour: str
    bounding_box: BoundingBox
    artwork: str | None = None
    """Rare, explicit override: this placement's ink regardless of what
    artwork resolution would otherwise pick for this colour elsewhere."""


class MultipleTemplate(BaseModel):
    """Several garments in one photo. ``displace``/``shade`` are scene-level
    only -- one photo, one lighting pass; a placement needing different
    rendering treatment belongs in its own template instead."""

    model_config = ConfigDict(frozen=True)

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
    displace: DisplaceConfig = DisplaceConfig()
    shade: ShadeConfig = ShadeConfig()

    def render_config_for(self, placement: Placement) -> RenderConfig:
        return RenderConfig(
            bounding_box=placement.bounding_box, displace=self.displace, shade=self.shade
        )


class SingleTemplate(BaseModel):
    """One photo, one garment -- a lifestyle shot, a folded product photo,
    anything that isn't part of a colour set."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["single"] = "single"
    colour: str | None = None
    """Optional context -- which garment colour this depicts, for artwork
    resolution. There's only one photo, so nothing needs it to disambiguate a
    filename."""
    artwork: str | None = None
    bounding_box: BoundingBox
    displace: DisplaceConfig = DisplaceConfig()
    shade: ShadeConfig = ShadeConfig()

    def render_config(self) -> RenderConfig:
        return RenderConfig(
            bounding_box=self.bounding_box, displace=self.displace, shade=self.shade
        )


AnyTemplate = ColourMatrixTemplate | MultipleTemplate | SingleTemplate
"""One loaded ``template.yaml``, whichever kind it turned out to be.

The plain union, for annotating variables and return types. Use
:data:`TemplateConfig` -- the same union carrying pydantic's discriminator --
wherever pydantic itself does the dispatch (a FastAPI ``response_model``, a
request body, a ``TypeAdapter``)."""

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
