"""Absolute mockup-only positions (ADR-0058); geometry reuses template.yaml's schema."""

from pydantic import BaseModel, ConfigDict

from etsy_listings.core.render.config import BoundingBox, LayerBoxes


class BoxPosition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    bounding_box: BoundingBox


class PlacementPositions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    placements: dict[str, BoxPosition]


TemplatePositions = dict[str, BoxPosition | PlacementPositions]
"""Template name to one box (single/colour-matrix) or placement-ID boxes (multiple).

No discriminator is written: these mutually exclusive shapes mirror template.yaml.
Membership and current geometry are deployment checks, so stale positions still save.
"""


def layer_boxes(positions: TemplatePositions | None, template: str) -> LayerBoxes:
    """The listing's boxes for ``template``'s layers, as
    :func:`~etsy_listings.core.render.config.scene_layers` takes them: the
    effective box of a layer is the listing's when stored, else the template's.

    A shape the template's kind does not take keys no layer and so moves
    nothing; validation refuses it before anything renders (spec rules 3–4).
    """
    match (positions or {}).get(template):
        case BoxPosition(bounding_box=box):
            return {None: box}
        case PlacementPositions(placements=placements):
            return {placement_id: p.bounding_box for placement_id, p in placements.items()}
        case _:
            return {}
