"""API request/response shapes. Template CRUD (list/get/put config) reuses
:mod:`etsy_listings.render.config`'s models directly -- ``template.yaml`` *is*
what the calibrator edits, so there is no meaningful wire-schema divergence to
keep separate here, unlike the preview endpoint's request shapes below (which
add a ``design`` selector nothing in the engine's config needs).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from etsy_listings.config.listing import Listing
from etsy_listings.render.config import BoundingBox, DisplaceConfig, Placement, ShadeConfig

TemplateKind = Literal["colour-matrix", "multiple", "single"]

DesignSource = Literal["bundled", "upload"]


class DesignSummary(BaseModel):
    """One entry in the calibrator's test-design library (A19).

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
    width: int | None = None
    height: int | None = None
    """The template photo's **true** pixel size, or ``None`` for a directory
    with no photo in it yet.

    The editor renders its canvas downscaled (``?scale=editor``), so the
    preview image it draws is no longer the answer to "what coordinate space
    are these boxes in?" -- ``template.yaml`` stores them at the photo's true
    size, and this is where the client learns what that is. Measuring the
    displayed image instead is the bug this field exists to make impossible:
    it would silently write every box a few times too small."""


class AssignKindRequest(BaseModel):
    kind: TemplateKind


class SwatchResponse(BaseModel):
    """A colour-matrix colour's real garment shade, sampled off its own scene
    photo (`render/swatch.py`'s `sample_swatch`) rather than an invented or
    hand-typed hex value -- nothing in the domain model stores one."""

    hex: str


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


# ──────────────────────────────────────────────────────────────────────────
# Listings UI (phase 5). ListingDetail reuses `Listing` directly for the
# read/write body -- the wire shape *is* listing.yaml -- the same rule
# TemplateSummary above follows for template.yaml.
# ──────────────────────────────────────────────────────────────────────────

IssueSeverity = Literal["block", "warn"]
IssueTab = Literal["variants", "images", "details"]


class Issue(BaseModel):
    severity: IssueSeverity
    tab: IssueTab
    where: str
    message: str


class IssueCounts(BaseModel):
    block: int
    warn: int


ListingStatus = Literal["draft", "published"]
"""Derived on every read, never persisted -- `published` iff a lockfile
exists and carries an Etsy listing id, the same "derived" principle already
stated for `TemplateSummary.status`."""


class ListingSummary(BaseModel):
    name: str
    garment_profile: str
    design: str | None
    """The design's name, as `GET /api/listing-designs/{name}/thumbnail`
    takes it -- so the table can show the artwork without a second round
    trip per row. ``None`` when `Listing.design` carries more than one
    artwork key (``on-light``/``on-dark``): there is then no single picture
    that stands for the listing, and an arbitrary pick would show the wrong
    ink half the time."""
    colour_count: int
    status: ListingStatus
    issue_counts: IssueCounts
    etsy_listing_id: int | None = None
    printify_product_id: str | None = None
    """Carried on the summary, not just on `ListingDetail`, because the table
    offers the same "Open on Etsy / Printify" menu the editor's page head
    does -- and a menu per row that each had to fetch its own ids would be one
    request per listing to render a list."""


class ResolvedPrice(BaseModel):
    size: str
    amount: str
    """Formatted as `Money` prints itself, e.g. ``"249 NOK"``."""


class ListingDetail(Listing):
    """The full `Listing`, plus what the editor needs and nothing a listing
    itself would ever store: computed status, computed issues, and (only
    meaningful right after a PATCH) which fields a rejected candidate failed
    on."""

    name: str
    status: ListingStatus
    issues: list[Issue]
    field_errors: dict[str, str] = {}
    """Populated only when a PATCH's candidate failed `Listing.model_validate`
    -- the write was skipped and every other field here still describes the
    listing as it was before the PATCH. Empty on every GET and every
    successful PATCH; the frontend never re-implements this validation; it
    only renders what the server returns."""
    etsy_listing_id: int | None = None
    printify_product_id: str | None = None
    pricing_plan_name: str | None = None
    """The resolved plan's filename stem, for display -- selecting a
    different plan from the UI is deferred (phase-5-listings-ui.md)."""
    resolved_prices: list[ResolvedPrice] = []


class GarmentProfileSummary(BaseModel):
    name: str
    sizes: list[str]
    colors: dict[str, Literal["light", "dark"]]


class PricingPlanSummary(BaseModel):
    name: str
    garment_profile: str
    compatible: bool
    """Whether this plan declares the exact garment profile asked for --
    mirrors `newcmd.logic.build_pricing_plan_choices`'s marker."""


class ListingDesignSummary(BaseModel):
    name: str
    file: str
    """Workspace-relative path under ``designs/``, e.g.
    ``designs/take-a-hike.png``."""


class CommonMediaSummary(BaseModel):
    """One shared asset under ``common-media/`` -- the other half of `media:`,
    a bare path rather than a rendered mockup."""

    name: str
    file: str
    """Workspace-relative, for display: ``common-media/size-guide.png``."""
    ref: str
    """Listing-relative, ready to write into `media:` unchanged. A bare media
    entry resolves against the listing's own directory (PRD 8a), the same rule
    `design:` follows, so the picker hands back the stored form rather than
    leaving every caller to rebuild it."""


class WorkspaceSummary(BaseModel):
    """Which workspace the UI is pointed at. One workspace is one shop, so the
    sidebar names it -- the difference between a test shop and the real one is
    worth seeing before an edit, not after an apply."""

    shop_name: str | None
    """`etsy.shop_name` from `shop.yaml`. ``None`` until `setup` reads it back
    from Etsy (PRD 51), which a workspace that has only ever rendered mockups
    never has."""


class CreateListingRequest(BaseModel):
    name: str
    design: str
    """A design's ``name`` from `GET /api/listing-designs`."""
    garment_profile: str
    colors: list[str]
