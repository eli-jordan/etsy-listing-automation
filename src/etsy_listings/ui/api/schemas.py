"""API request/response shapes. Template CRUD (list/get/put config) reuses
:mod:`etsy_listings.render.config`'s models directly -- ``template.yaml`` *is*
what the calibrator edits, so there is no meaningful wire-schema divergence to
keep separate here, unlike the preview endpoint's request shapes below (which
add a ``design`` selector nothing in the engine's config needs).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from etsy_listings.ai.proposals import (
    ListingProposal as ListingProposal,
)
from etsy_listings.ai.proposals import (
    Resolution,
)
from etsy_listings.batches import AiState
from etsy_listings.config.listing import Listing
from etsy_listings.config.listing_template import ListingTemplate
from etsy_listings.config.media import MediaEntry, MediaKind

# ``draft``/``deployed``/``live``/``dirty``, imported rather than restated:
# the lifecycle rule is the engine's (the UI's badge and Phase 6's `status`
# command have to agree on it), and a second `Literal` here would be a second
# place a state could be added to. Derived on every read, never persisted --
# the same principle `TemplateSummary.status` states below.
from etsy_listings.engine.status import ListingGesture, ListingStatus
from etsy_listings.render.config import BoundingBox, DisplaceConfig, Placement, ShadeConfig
from etsy_listings.ui.runs.events import ApplyRunPhase, PlanRunPhase, RunEvent, RunScope

TemplateKind = Literal["colour-matrix", "multiple", "single"]

DesignSource = Literal["bundled", "upload"]


class DesignSummary(BaseModel):
    """One entry in the calibrator's test-design library.

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
the configuration does not need -- as well as something that could disagree with the
config sitting next to it."""


class TemplatePhoto(BaseModel):
    """One scene photo in a template's directory: which colour it is, and where
    it actually is.

    ``file`` is workspace-relative and forward-slashed, resolved through
    ``Workspace.scene_photo`` -- the same rule the renderer uses, including the
    trailing-segment fallback for a vendor pack delivered as
    ``{template}-{colour}.png``. The listings editor shows it under its preview
    so the user knows which file to go and edit, and it used to *derive* that
    caption from ADR-0004's convention in TypeScript, which named a file that was
    not there for exactly the pack the fallback exists for.

    ``colour`` is ``None`` for a ``multiple``/``single`` template's fixed
    ``scene.png``: there is no per-colour name to derive one from.
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

    Reporting only: ADR-0004 makes the filename the source of truth, so there is
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
    ``GET.../config`` response (which includes ``kind``) into the body."""

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

IssueSeverity = Literal["block", "warn", "info"]
"""`listing_validation.Severity` on the wire. ``info`` (ADR-0045's stripped
audio) is shown quietly and counted nowhere: `IssueCounts` stays blocks and
warnings, the two a seller has to act on."""
IssueTab = Literal["variants", "pricing", "images", "details"]


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
    offers the same "Open in Etsy / Printify" menu the editor's page head
    does -- and a menu per row that each had to fetch its own ids would be one
    request per listing to render a list."""
    gestures: list[ListingGesture] = []
    """Which buttons the listings table offers for this row. Computed
    server-side from the same facts as ``status``, so the CLI's future
    `status` and the table cannot disagree about the row. The editor's
    `ListingDetail` carries the same list for its action row."""


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
    gestures: list[ListingGesture] = []
    """The lifecycle actions the editor's action row offers: the listings
    table's row gestures, from the same rule. Empty for the unsaved
    draft, which has no lifecycle yet."""
    """Populated only when a PATCH's candidate failed `Listing.model_validate`
    -- the write was skipped and every other field here still describes the
    listing as it was before the PATCH. Empty on every GET and every
    successful PATCH; the frontend never re-implements this validation; it
    only renders what the server returns."""
    etsy_listing_id: int | None = None
    printify_product_id: str | None = None
    pricing_plan_name: str | None = None
    """The resolved plan's filename stem, for display -- selecting a
    different plan from the UI is deferred (features/listings-ui-20260915/spec.md)."""
    resolved_prices: list[ResolvedPrice] = []
    garment_materials: list[str] | None = None
    """Read-only fibre materials from the selected garment profile.

    They remain outside ``Listing`` because a listing never writes or owns
    them; this derived field merely lets the editor show what Etsy will use.
    """
    # Profile context sent to AI SEO generation, including edits that leave
    # the profile name and materials unchanged.
    garment_product_type: str | None = None
    garment_brand: str | None = None
    garment_model: str | None = None
    description_composed: str = ""
    """The final `etsy.description` text, exactly as
    `Workspace.compose_description` joins it -- the one value the Details
    tab's preview may render, so it never re-implements the lead/body join
    itself (AI SEO implementation plan, PR6). Falls back to the lead alone
    when `ref` fails to resolve; `description_ref_error`-derived issues
    already say why, so this field only avoids also raising."""
    design_content_hash: str | None = None
    """Hash of selected design refs and bytes, for AI proposal staleness.
    Unreadable files contribute a stable marker; absent only with no design."""

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
    materials: list[str] | None = None
    colors: dict[str, Literal["light", "dark"]]
    preview_template: str | None = None
    """A ``colour-matrix`` template the Variants tab uses to judge colours
    . Null when the garment profile does not name one -- the editor
    does not fall back to ``media:``."""


class PricingPlanSummary(BaseModel):
    name: str
    garment_profile: str
    compatible: bool
    """Whether this plan declares the exact garment profile asked for --
    mirrors `newcmd.logic.build_pricing_plan_choices`'s marker."""
    ref: str
    """Workspace-rooted, ready to PATCH straight into `pricing_plan:`
    unchanged -- `newcmd.logic.pricing_plan_ref`'s write-side form, the same
    rule `MediaFileSummary.ref` follows for a shared image."""


class ListingDesignSummary(BaseModel):
    name: str
    file: str
    """Workspace-relative path under ``designs/``, e.g.
    ``designs/take-a-hike.png``."""


class MediaFileSummary(BaseModel):
    """One file a listing can put in `media:` as a file ref: a
    shared one under ``common-media/``, or one of the listing's own. A bare
    file uploaded as-is, rather than a rendered mockup."""

    name: str
    """Its path under the directory it was listed from -- ``common-media/``
    or the listing's own -- which is what the picture endpoints take."""
    file: str
    """Workspace-relative, for display: ``common-media/size-guide.png``,
    ``listings/take-a-hike/close-up.mp4``."""
    ref: str
    """The ref to write into `media:` unchanged. A shared file's ref is its
    workspace-relative path, so it equals ``file``; a listing's own file is
    spelled ``./close-up.mp4``, which is why this is a field of its
    own rather than something callers build."""
    kind: MediaKind
    """``image`` or ``video``, as `config.media.media_kind` classifies it --
    served rather than re-derived in the browser, so the locator and the
    gallery rules cannot disagree about a ``.MOV``."""


class CommonCopySummary(BaseModel):
    """One `common-copy/*.md` file, for the Description tab's body-source
    selector (AI SEO implementation plan, PR6). A common-copy ref is
    workspace-relative, like every other ref, so it is exactly what
    `description.ref` stores, already usable as-is."""

    ref: str
    """Workspace-relative, e.g. ``common-copy/comfort-colors.md`` -- what
    `description.ref` stores unchanged."""
    title: str
    """The file's front-matter title, for the picker's option label."""
    summary: str | None = None
    """The file's optional front-matter summary, for the metadata display
    once one is selected."""


class EtsySectionSummary(BaseModel):
    """One row for the Details tab's Section dropdown.

    Existing rows come from the unscoped `EtsyShopClient.shop_sections`;
    creating one returns the same shape through the signed-in client.
    """

    id: int
    title: str


class EtsySectionsResponse(BaseModel):
    """The section picker's rows and whether Etsy could supply them.

    ``available`` distinguishes a configured shop with no sections -- where
    the editor can create the first one -- from a workspace that must retain
    the plain-text fallback because its Etsy connection is unavailable.
    """

    available: bool
    sections: list[EtsySectionSummary]


class CreateEtsySectionRequest(BaseModel):
    """The title Etsy should give a newly created shop section."""

    title: str = Field(min_length=1)

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class WorkspaceSummary(BaseModel):
    """Which workspace the UI is pointed at. One workspace is one shop, so the
    sidebar names it -- the difference between a test shop and the real one is
    worth seeing before an edit, not after an apply."""

    shop_name: str | None
    """`etsy.shop_name` from `shop.yaml`. ``None`` until `setup` reads it back
    from Etsy, which a workspace that has only ever rendered mockups
    never has."""
    storage_id: str
    """Opaque identity of the workspace root for browser-only pending proposals
    . Distinct roots must not share a local-storage key merely because
    they use the same Etsy shop name."""


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
# Listing templates (ADR-0047, template completeness). The detail reuses `ListingTemplate` directly,
# as `ListingDetail` reuses `Listing`: the wire shape *is* template.yaml.
# ──────────────────────────────────────────────────────────────────────────


class PixelSize(BaseModel):
    width: int
    height: int


class ListingTemplateSummary(BaseModel):
    """One card on the Listing templates page (UI doc §2)."""

    name: str
    garment: str
    """The garment profile's blueprint as a seller names it --
    ``Comfort Colors 1717`` -- or the profile's own name when it will not
    load."""
    colour_count: int
    pricing_plan_name: str | None
    """The plan ref's filename stem; ``None`` when the template prices its
    sizes itself."""
    media: list[MediaEntry]
    batch_count: int = 0
    """Batches made from this template, while their records last."""
    design_minimum: PixelSize | None = None
    """The smallest design the garment's print area takes -- New batch's size
    hint (UI doc §4). ``None`` when the garment profile will not load."""


class ListingTemplateSource(BaseModel):
    kind: Literal["listing", "listing-template"]
    name: str


class ListingTemplateAsset(BaseModel):
    """A file the draft will copy: the ``./`` ref the template will name it
    by, and the ref it has in its source -- which is where the *name it*
    page's thumbnail has to come from, since the copy does not exist yet."""

    ref: str
    source_ref: str


class ListingTemplateDetail(ListingTemplate):
    """A listing template as its pages read it, saved or not -- one shape for
    both, as `ListingDetail` is one shape for a listing and the unnamed draft.

    A draft (``GET /draft``: Save as listing template or Clone, written
    nowhere, UI doc §1) has ``name`` ``""``, no ``modified_at``, and says
    where it came from in ``source`` and ``assets``."""

    name: str
    modified_at: datetime | None
    issues: list[Issue]
    garment: str | None = None
    pricing_plan_name: str | None = None
    source: ListingTemplateSource | None = None
    assets: list[ListingTemplateAsset] = []
    # What the listing editor's tabs read off a `ListingDetail`, computed the
    # same way, because the listing-template editor mounts those tabs
    # unchanged (UI doc §3, *Existing components the template editor needs*).
    resolved_prices: list[ResolvedPrice] = []
    garment_materials: list[str] | None = None
    garment_product_type: str | None = None
    garment_brand: str | None = None
    garment_model: str | None = None
    description_composed: str = ""
    """The body alone: a template has no lead, and each listing's own is
    placed above it."""


class ListingTemplateSaveResult(BaseModel):
    """What a create or ``PUT`` did. Refusing an incomplete document is
    a 200 with ``saved: false``, as a listing's malformed PATCH is, because the
    editor shows the issues and keeps going; nothing was written."""

    saved: bool
    issues: list[Issue]
    field_errors: dict[str, str] = {}
    template: ListingTemplateDetail | None = None


class CreateListingTemplateRequest(BaseModel):
    """Save as listing template (``from_listing``) or Clone
    (``from_template``) -- exactly one. There is no blank creation (spec)."""

    name: str
    from_listing: str | None = None
    from_template: str | None = None
    document: dict[str, Any] | None = None
    """The seller's edits made before naming it, as ``template.yaml`` would
    hold them: the *name it* state is the editor (UI doc §1, §3). Absent
    means the draft as the source gives it. Checked as a ``PUT`` is,
    and its ``./`` refs must be files the draft copies."""

    @model_validator(mode="after")
    def _exactly_one_source(self) -> CreateListingTemplateRequest:
        if (self.from_listing is None) == (self.from_template is None):
            raise ValueError("give exactly one of from_listing and from_template")
        return self


# ──────────────────────────────────────────────────────────────────────────
# Staging and batches (cache-record persistence; batch plan PR 2).
# ──────────────────────────────────────────────────────────────────────────


class StagingRowDetail(BaseModel):
    """One unique design on the staging page (UI doc §5)."""

    id: str
    sources: list[str]
    """Every uploaded file with these bytes; more than one is a merge."""
    name: str
    typed: bool
    state: Literal["ready", "name", "invalid"]
    """``ready`` will be created; ``name`` blocks Create until fixed;
    ``invalid`` will not be created and blocks nothing."""
    message: str | None
    note: str | None
    suggestion: str | None
    reuse: str | None
    """The ``designs/`` stem with this row's exact bytes, which its listing
    will name instead of writing its own (spec, *Content deduplication*)."""


class AiReadinessBlock(BaseModel):
    """Why a batch could not draft if it were created now (spec, *Design
    validation*; ``staging.note.md``): the sentence after *AI drafting can't
    run yet.*, and what to do about it."""

    message: str
    remedy: str


class StagingDetail(BaseModel):
    id: str
    listing_template: str
    label: str
    template_saved_at: datetime
    """When the frozen listing template was last saved: *Using X as saved at
    HH:MM*."""
    expires_at: datetime
    rows: list[StagingRowDetail]
    ignored: list[str]
    """A ZIP's files that are not PNGs, by their path in it: the count
    strip's *N other files ignored* and its list (UI doc §5)."""
    ai_blocked: AiReadinessBlock | None = None
    """Set only while a prompt, a ready provider or Etsy market access is
    missing, which refuses Create; nothing is said when AI can run."""


class StagingRefusal(BaseModel):
    """A ``422``'s ``detail`` for an upload refused before staging."""

    message: str
    remedy: str


class StagingPatch(BaseModel):
    """Every staging edit, applied in order: label, names, removals."""

    label: str | None = None
    names: dict[str, str] = {}
    remove: list[str] = []


StepId = Literal["brief", "market", "seo"]
StepState = Literal["pending", "active", "done", "skipped", "warning", "failed"]


class WorkflowStep(BaseModel):
    """One node of the three-node indicator (``AiWorkflowIndicator.tsx``'s
    ``WorkflowStep``): an AI run's, or a batch row's."""

    id: StepId
    state: StepState
    detail: str | None = None


class BatchRowDetail(BaseModel):
    id: str
    sources: list[str]
    name: str
    """The name actually created, which confirm may have suffixed."""
    design: str
    creation: Literal["pending", "created", "failed"]
    error: str | None
    ai: AiState | None = None
    """The row's AI work (ADR-0048, and ADR-0050's ``cancelled_by_deploy``); ``None``
    until its listing exists."""
    ai_steps: list[WorkflowStep] = []
    """The live run's nodes while running, else the last run's as it ended."""
    ai_error: str | None = None
    queue_position: int | None = None
    """1 for the next row to start, across every batch; ``None`` unless
    queued."""
    proposal: Literal["ready", "stale", "resolved"] | None = None
    """The listing's cached proposal: sections waiting and current,
    waiting but out of date, or every section dealt with."""
    stale_reasons: list[str] = []
    reviewed: bool = False
    """The seller's own judgement (spec, *Review workflow*)."""
    reviewable: bool = False
    """Whether Mark reviewed is offered: not on a queued, drafting, deleted
    or never-created row (UI doc §7)."""
    deleted: bool = False
    """The listing was deleted; the row stays, struck through."""


BatchStatus = Literal["staging", "drafting", "in_review", "complete", "stopped"]
"""Recent batches' derived status (UI doc §2): ``staging`` for a session not
confirmed yet, the rest `batches.standing`'s."""


class BatchDetail(BaseModel):
    id: str
    label: str
    listing_template: str
    created_at: datetime
    rows: list[BatchRowDetail]
    concurrency: int = 1
    """``batch_ai.concurrency``: how many rows draft at once."""
    status: BatchStatus = "drafting"


class BatchPatch(BaseModel):
    """Rename the batch (UI doc §7): its label only, never its identity."""

    label: str


class ReviewedRequest(BaseModel):
    reviewed: bool


class BatchIndexEntry(BaseModel):
    """One row of Recent batches (UI doc §2): a confirmed batch, or a staging
    session not confirmed yet, which reopens staging instead."""

    kind: Literal["staging", "batch"]
    id: str
    label: str
    listing_template: str
    created_at: datetime
    status: BatchStatus
    designs: int
    """Rows: the staged designs, or the batch's rows."""
    listings: int = 0
    """Rows with a listing now: created and not deleted."""
    drafted: int = 0
    reviewed: int = 0
    undrafted: int = 0
    """Listings **Cancel batch** left for Resume."""
    failures: int = 0
    """*N need retry*: a count beside the progress, never a status."""
    expires_at: datetime | None = None
    """A staging session's: seven days after its last edit."""


class ListingBatch(BaseModel):
    """The batch a listing was made by, for the editor's row above the head
    (UI doc §8): Back to batch and Mark reviewed."""

    batch_id: str
    label: str
    row_id: str
    reviewed: bool
    reviewable: bool


# ──────────────────────────────────────────────────────────────────────────
# Runs. ``RunEvent`` itself, and the ``Plan``/``StagePlan`` DTOs it
# carries, live in ``ui/runs/events.py`` beside the engine types they mirror --
# only the request/response envelope belongs here, next to every other
# endpoint's shapes.
# ──────────────────────────────────────────────────────────────────────────


class _CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListingPlanRequest(_CreateRunRequest):
    kind: Literal["plan"]
    scope: Literal["listings"]
    listings: list[str] = Field(min_length=1)


class WorkspacePlanRequest(_CreateRunRequest):
    kind: Literal["plan"]
    scope: Literal["workspace"]


class ListingApplyRequest(_CreateRunRequest):
    kind: Literal["apply"]
    scope: Literal["listings"]
    listings: list[str] = Field(min_length=1)
    expect: dict[str, str]


class WorkspaceApplyRequest(_CreateRunRequest):
    kind: Literal["apply"]
    scope: Literal["workspace"]
    listings: list[str]
    expect: dict[str, str]
    reviewed_run_id: str


CreateRunRequest = (
    ListingPlanRequest | WorkspacePlanRequest | ListingApplyRequest | WorkspaceApplyRequest
)


class _RunSummary(BaseModel):
    """Enough to show a page-head control (decision 8's table) or a row in a
    future batch view -- everything except the event log itself."""

    id: str
    scope: RunScope
    listings: list[str]
    seen: bool
    reviewed_run_id: str | None
    created_at: datetime


class PlanRunSummary(_RunSummary):
    kind: Literal["plan"]
    phase: PlanRunPhase
    reviewed_run_id: None = None


class ApplyRunSummary(_RunSummary):
    kind: Literal["apply"]
    phase: ApplyRunPhase


RunSummary = Annotated[PlanRunSummary | ApplyRunSummary, Field(discriminator="kind")]


class PlanRunDetail(PlanRunSummary):
    events: list[RunEvent]
    """Every event this run has produced so far, in order -- what a client
    reattaching to an in-progress or just-finished run replays instead of
    opening the SSE stream from nothing (decision 9)."""


class ApplyRunDetail(ApplyRunSummary):
    events: list[RunEvent]


RunDetail = Annotated[PlanRunDetail | ApplyRunDetail, Field(discriminator="kind")]


# ──────────────────────────────────────────────────────────────────────────
# AI SEO (AI SEO implementation plan, PR5; ADR-0049). A proposal is cached on the
# server (`ai/proposals.py`) and reaches the browser two ways: as an AI
# run's `proposal` event (`ui/airuns/events.py`) the moment it is written,
# and from `GET /api/listings/{name}/proposal` after that. Both are
# :class:`ListingProposal`. The choices' field shapes mirror
# `ai/models.py.SeoProposal` field for field, the same "wire shape *is* the
# domain shape" rule `ListingDetail` follows for `Listing` above; they live
# in `ai/proposals.py` because the cache record is made of them.
# ──────────────────────────────────────────────────────────────────────────


class SeoReadinessResponse(BaseModel):
    """Whether AI Mode can be enabled for one saved listing right now
    (implementation plan, "Entry point"). The frontend leaves the control
    visible and disabled when ``ready`` is false; ``reason`` explains why
    to a developer or support reader."""

    ready: bool
    reason: str | None = None
    batch_pending: bool = False
    """A batch row owns this listing's AI: the editor follows the
    batch run instead of offering its own."""
    deploying: bool = False
    """A UI plan or apply holds this listing: the editor asks again
    until the deploy lets it go."""


class ProposalResolutionPatch(BaseModel):
    """``PATCH /api/listings/{name}/proposal/resolution``: the sections to
    record, on the proposal generated at ``generated_at`` -- a regeneration
    that landed meanwhile is a different proposal, and is a 409. ``pending``
    reopens a section."""

    generated_at: datetime
    title: Resolution | None = None
    tags: Resolution | None = None
    lead: Resolution | None = None
