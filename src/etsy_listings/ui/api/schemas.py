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

DesignSource = Literal["bundled", "upload"]


class DesignSummary(BaseModel):
    """One entry in the calibrator's test-design library (A16).

    ``bundled-grid``: the grid/ruler target, for spotting warp/displacement
    errors. ``bundled-on-light``/``bundled-on-dark``: deterministic
    ink-coloured targets, so a mis-resolved artwork is visually obvious in the
    calibrator, not just described in a diff. ``upload``: a PNG the user added,
    for judging a real ink weight on a real garment -- the question the grid
    cannot answer.
    """

    id: str
    label: str
    source: DesignSource


TemplateStatus = Literal["needs-calibration", "calibrated"]
"""Whether a template is ready to render from. Derived on every read, never
stored: the calibrator's rail sorts unfinished templates to the top, and a
persisted ``calibrated:`` flag in ``template.yaml`` would be new product state
no PRD decision covers -- as well as something that could disagree with the
config sitting next to it."""


class TemplateSummary(BaseModel):
    name: str
    kind: TemplateKind | None
    colours: list[str]
    has_config: bool
    status: TemplateStatus
    status_reason: str | None = None
    """Why it is not calibrated yet, in the words the rail shows the user
    ("no kind set", "no boxes", "1 box has no colour"). ``None`` when
    ``status`` is ``calibrated`` -- there is nothing to explain."""


class UploadResponse(BaseModel):
    name: str
    kind: TemplateKind | None
    """``None`` when the upload did not name a kind. Wireframe 2a asks for it
    afterwards, as the first calibration step, so the photos are on screen
    when the question is put -- which is the only way it is answerable for a
    set someone else assembled."""
    colours: list[str]


class AssignKindRequest(BaseModel):
    kind: TemplateKind


class ColourReportRow(BaseModel):
    """What one photo in a candidate ``colour-matrix`` set will be taken as.

    Reporting only: PRD 7a makes the filename the source of truth, so there is
    no manual mapping to offer and nothing here changes a name.
    """

    filename: str
    colour: str
    clean: bool
    """False when the filename is not already the slug -- ``Heather Grey.png``
    still yields ``heather-grey``, but not the name sitting on disk, and the
    user should hear that from the calibrator rather than discover it later."""


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
    design: str = "bundled-grid"


class MultiplePreviewRequest(BaseModel):
    placements: list[Placement]
    displace: DisplaceConfig = DisplaceConfig()
    shade: ShadeConfig = ShadeConfig()
    design: str = "bundled-grid"


class SinglePreviewRequest(BaseModel):
    bounding_box: BoundingBox
    displace: DisplaceConfig = DisplaceConfig()
    shade: ShadeConfig = ShadeConfig()
    design: str = "bundled-grid"


PreviewRequest = ColourMatrixPreviewRequest | MultiplePreviewRequest | SinglePreviewRequest
"""Which shape applies is decided by which kind the target template already
is -- the endpoint validates the body against that one kind's model, rather
than relying on shape-sniffing across all three."""
