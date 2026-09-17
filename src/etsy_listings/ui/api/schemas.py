"""API request/response shapes. Template CRUD (list/get/put config) reuses
:mod:`etsy_listings.render.config`'s models directly -- ``template.yaml`` *is*
what the calibrator edits, so there is no meaningful wire-schema divergence to
keep separate here, unlike the preview endpoint's request shapes below (which
add a ``design`` selector nothing in the engine's config needs).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from etsy_listings.config.listing import Listing

# ``draft``/``deployed``/``live``/``dirty``, imported rather than restated:
# the lifecycle rule is the engine's (the UI's badge and Phase 6's `status`
# command have to agree on it), and a second `Literal` here would be a second
# place a state could be added to. Derived on every read, never persisted --
# the same principle `TemplateSummary.status` states below.
from etsy_listings.engine.status import ListingGesture, ListingStatus
from etsy_listings.render.config import BoundingBox, DisplaceConfig, Placement, ShadeConfig
from etsy_listings.ui.runs.events import RunEvent, RunKind, RunPhase

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


class TemplatePhoto(BaseModel):
    """One scene photo in a template's directory: which colour it is, and where
    it actually is.

    ``file`` is workspace-relative and forward-slashed, resolved through
    ``Workspace.scene_photo`` -- the same rule the renderer uses, including the
    trailing-segment fallback for a vendor pack delivered as
    ``{template}-{colour}.png``. The listings editor shows it under its preview
    so the user knows which file to go and edit, and it used to *derive* that
    caption from PRD 7a's convention in TypeScript, which named a file that was
    not there for exactly the pack the fallback exists for.

    ``colour`` is ``None`` for a ``multiple``/``single`` template's fixed
    ``scene.png``: there is no per-colour name to derive one from (PRD 28).
    """

    colour: str | None
    file: str


class TemplateSummary(BaseModel):
    name: str
    kind: TemplateKind | None
    colours: list[str]
    photos: list[TemplatePhoto] = []
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
    gestures: list[ListingGesture] = []
    """Which buttons the listings table offers for this row (PRD 66). Computed
    server-side from the same facts as ``status``, so the CLI's future
    `status` and the table cannot disagree about the row. Empty on the
    editor's `ListingDetail` -- those buttons do not exist there."""


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
    modified_at: datetime | None
    """UTC modification time of ``listing.yaml``. ``None`` for an unsaved
    draft, which has no file yet."""
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

    @model_validator(mode="after")
    def _require_a_price_source(self) -> ListingDetail:
        """Describing a listing never re-decides whether it may be *written*.

        A listing with neither ``pricing_plan`` nor ``prices`` is exactly the
        state the editor exists to get a user out of -- it is what
        ``GET /api/listing-draft`` hands back and what a refused create comes
        back as -- so a description of it that refuses to render is a page that
        cannot show the problem it is reporting. The write paths
        (``Listing.load``, the PATCH, the POST) all validate a ``Listing``, not
        this, and are unaffected.

        Shadowing works because pydantic v2 collects validators by attribute
        name across the MRO, so this replaces the parent's. That is a hazard in
        general -- it is why `Listing` keeps its other five rules in a
        differently-named validator this cannot touch -- and the whole reason
        the price-source rule stands alone there.
        """
        return self


class GarmentProfileSummary(BaseModel):
    name: str
    sizes: list[str]
    colors: dict[str, Literal["light", "dark"]]
    preview_template: str | None = None
    """A ``colour-matrix`` template the Variants tab uses to judge colours
    (A13). Null when the garment profile does not name one -- the editor
    does not fall back to ``media:``."""


class PricingPlanSummary(BaseModel):
    name: str
    garment_profile: str
    compatible: bool
    """Whether this plan declares the exact garment profile asked for --
    mirrors `newcmd.logic.build_pricing_plan_choices`'s marker."""
    ref: str
    """Listing-relative, ready to PATCH straight into `pricing_plan:`
    unchanged -- `newcmd.logic.pricing_plan_ref`'s write-side form, the same
    rule `CommonMediaSummary.ref` follows for a shared image."""


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


class EtsySectionSummary(BaseModel):
    """One row for the Details tab's Section dropdown, from
    `EtsyShopClient.shop_sections` -- unscoped, so this needs only the
    workspace's app key pair, never a signed-in Etsy session."""

    id: int
    title: str


class WorkspaceSummary(BaseModel):
    """Which workspace the UI is pointed at. One workspace is one shop, so the
    sidebar names it -- the difference between a test shop and the real one is
    worth seeing before an edit, not after an apply."""

    shop_name: str | None
    """`etsy.shop_name` from `shop.yaml`. ``None`` until `setup` reads it back
    from Etsy (PRD 51), which a workspace that has only ever rendered mockups
    never has."""


class DraftListingRequest(BaseModel):
    """A candidate ``listing.yaml``, as the editor holds it before the listing
    exists.

    ``dict`` rather than ``Listing``, deliberately: an incomplete candidate is
    the *normal* case on this endpoint, and rejecting it at the FastAPI boundary
    would answer with a 422 the editor cannot render. The point is to get it as
    far as ``Listing.draft`` and report what is missing."""

    document: dict[str, Any] = Field(default_factory=dict)


class CreateListingRequest(BaseModel):
    """The whole document, not a handful of fields to build one from.

    The editor is the create form, so by the time a name is typed the user may
    have chosen a design, colours and images -- and the shape they edited is the
    shape that should be written. A server-built stub here would be a second
    opinion about what a new listing starts as."""

    name: str
    document: dict[str, Any]


class RenameListingRequest(BaseModel):
    new_name: str


# ──────────────────────────────────────────────────────────────────────────
# Runs (A33). ``RunEvent`` itself, and the ``Plan``/``StagePlan`` DTOs it
# carries, live in ``ui/runs/events.py`` beside the engine types they mirror --
# only the request/response envelope belongs here, next to every other
# endpoint's shapes.
# ──────────────────────────────────────────────────────────────────────────


class CreateRunRequest(BaseModel):
    kind: RunKind
    listings: list[str]
    expect: dict[str, str] | None = None
    """A fingerprint per listing, from an earlier plan run's
    ``listing_planned`` event -- ``apply_listings``'s own A31 check. Absent
    for a plan run, and for an apply run with nothing to compare against."""


class RunSummary(BaseModel):
    """Enough to show a page-head control (decision 8's table) or a row in a
    future batch view -- everything except the event log itself."""

    id: str
    kind: RunKind
    listings: list[str]
    phase: RunPhase
    seen: bool


class RunDetail(RunSummary):
    events: list[RunEvent]
    """Every event this run has produced so far, in order -- what a client
    reattaching to an in-progress or just-finished run replays instead of
    opening the SSE stream from nothing (decision 9)."""
