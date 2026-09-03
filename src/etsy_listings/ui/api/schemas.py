"""API request/response shapes. Template CRUD (list/get/put config) reuses
:mod:`etsy_listings.render.config`'s models directly -- ``template.yaml`` *is*
what the calibrator edits, so there is no meaningful wire-schema divergence to
keep separate here, unlike the preview endpoint's request shapes below (which
add a ``design`` selector nothing in the engine's config needs).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from etsy_listings.render.config import BoundingBox, DisplaceConfig, Placement, ShadeConfig

TemplateKind = Literal["colour-matrix", "multiple", "single"]

BundledDesign = Literal["bundled-grid", "bundled-on-light", "bundled-on-dark"]
"""``bundled-grid``: the grid/ruler target, for spotting warp/displacement
errors. ``bundled-on-light``/``bundled-on-dark``: deterministic ink-coloured
targets, so a mis-resolved artwork is visually obvious in the calibrator, not
just described in a diff."""


class TemplateSummary(BaseModel):
    name: str
    kind: TemplateKind | None
    colours: list[str]
    has_config: bool


class UploadResponse(BaseModel):
    name: str
    kind: TemplateKind
    colours: list[str]


class ColourMatrixPreviewRequest(BaseModel):
    """Disambiguated from the other two preview shapes by required fields
    alone (``colour`` here, ``placements`` on ``MultiplePreviewRequest``,
    neither on ``SinglePreviewRequest``) -- extra fields are ignored rather
    than forbidden, since a natural client pattern is spreading a whole
    ``GET .../config`` response (which includes ``kind``) into the body."""

    colour: str
    bounding_box: BoundingBox
    displace: DisplaceConfig = DisplaceConfig()
    shade: ShadeConfig = ShadeConfig()
    design: BundledDesign = "bundled-grid"


class MultiplePreviewRequest(BaseModel):
    placements: list[Placement]
    displace: DisplaceConfig = DisplaceConfig()
    shade: ShadeConfig = ShadeConfig()
    design: BundledDesign = "bundled-grid"


class SinglePreviewRequest(BaseModel):
    bounding_box: BoundingBox
    displace: DisplaceConfig = DisplaceConfig()
    shade: ShadeConfig = ShadeConfig()
    design: BundledDesign = "bundled-grid"


PreviewRequest = ColourMatrixPreviewRequest | MultiplePreviewRequest | SinglePreviewRequest
"""Which shape applies is decided by which kind the target template already
is -- the endpoint validates the body against that one kind's model, rather
than relying on shape-sniffing across all three."""
