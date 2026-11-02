"""Absolute mockup-only positions (ADR-0058); geometry reuses template.yaml's schema."""

from pydantic import BaseModel, ConfigDict

from etsy_listings.core.render.config import BoundingBox


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
