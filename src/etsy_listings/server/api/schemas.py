from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from etsy_listings.core.ai.proposals import (
    ListingProposal as ListingProposal,
)
from etsy_listings.core.ai.proposals import (
    Resolution,
)
from etsy_listings.core.application.ai.events import (
    AiRunEvent,
    AiRunPhase,
)
from etsy_listings.core.application.ai.events import (
    WorkflowStep as WorkflowStep,
)
from etsy_listings.core.application.ai.readiness import (
    AiReadinessBlock as AiReadinessBlock,
)
from etsy_listings.core.application.backup_overview import BackupOverview, HistoryEntry
from etsy_listings.core.application.deploy.events import (
    ApplyRunPhase,
    PlanRunPhase,
    RunEvent,
    RunScope,
)
from etsy_listings.core.application.preparation.models import Action, Phase
from etsy_listings.core.backup.destinations import CopyOutcome
from etsy_listings.core.batches import AiState
from etsy_listings.core.config.listing import Listing
from etsy_listings.core.config.listing_template import ListingTemplate
from etsy_listings.core.config.media import MediaEntry, MediaKind
from etsy_listings.core.config.settings import (
    AiProviderSettings,
    BackupIntervalHours,
    BackupSettings,
    RetentionSettings,
    TemplatePositionLimits,
)
from etsy_listings.core.engine.status import ListingGesture, ListingStatus
from etsy_listings.core.render.config import BoundingBox, Placement, Renderer, TemplateConfig
from etsy_listings.core.workspace.calibration import MaskEdit, Stroke


class ApiModel(BaseModel):
    """A wire model whose field docstrings are its OpenAPI field descriptions."""

    model_config = ConfigDict(use_attribute_docstrings=True)


TemplateKind = Literal["colour-matrix", "multiple", "single"]

DesignSource = Literal["bundled", "upload"]


class DesignSummary(ApiModel):
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
"""Derived from the config on every read, never stored in ``template.yaml``."""


class TemplatePhoto(ApiModel):
    """One scene photo in a template's directory: which colour it is, and where
    it actually is.

    ``file`` is workspace-relative and forward-slashed, resolved through
    ``Workspace.scene_photo`` -- the same rule the renderer uses, including the
    trailing-segment fallback for a vendor pack delivered as
    ``{template}-{colour}.png``. The listings editor shows it under its preview
    so the user knows which file to go and edit.

    ``colour`` is ``None`` for a ``multiple``/``single`` template's fixed
    ``scene.png``: there is no per-colour name to derive one from.
    """

    colour: str | None
    file: str


class TemplateSummary(ApiModel):
    renderer: Literal["photo-warp", "marigold"] | None = None
    maps: MapReadinessResponse | None = None
    name: str
    kind: TemplateKind | None
    colours: list[str]
    photos: list[TemplatePhoto] = []
    has_config: bool
    status: TemplateStatus
    status_reason: str | None = None
    """Why it is not calibrated yet, in the words the rail shows ("no kind
    set", "1 box has no colour"); ``None`` when ``status`` is ``calibrated``."""
    width: int | None = None
    """The template photo's true pixel width, the space ``template.yaml``'s
    boxes are in, not the downscaled preview's; ``None`` with no photo yet."""
    height: int | None = None
    """The template photo's true pixel height, as ``width``."""
    labels: list[str] = []
    """The seller's words for finding this template; empty with no config yet."""


class AssignKindRequest(ApiModel):
    kind: TemplateKind


class SwatchResponse(ApiModel):
    """A colour-matrix colour's real garment shade, sampled off its own scene
    photo; nothing in the domain model stores one."""

    hex: str


class SceneCheckResponse(ApiModel):
    """Whether the Listing Images preview showed the wrong scene: one found
    under a pixel digest remembered from before a restart that no longer
    names the file's pixels. The digest is corrected either way."""

    changed: bool


class PositionedListingResponse(ApiModel):
    """A listing holding its own position for a template, which a
    recalibration may put outside the limits. ``placements`` lists the
    ``multiple`` placement IDs it positions; empty for one box."""

    listing: str
    placements: list[str]


class ColourReportRow(ApiModel):
    """What one photo in a candidate ``colour-matrix`` set will be taken as.

    Reporting only: the filename is the source of truth, so nothing here
    changes a name.
    """

    filename: str
    colour: str
    clean: bool
    """False when the filename is not already the slug: ``Heather Grey.png``
    yields ``heather-grey``."""


class ColourMatrixPreviewRequest(ApiModel):
    """A colour-matrix template's preview body. All three preview shapes take
    ``labels``: an editor preview names the labels of its
    ``calibration_revision`` with them. None draws them."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["colour-matrix"] = "colour-matrix"
    colour: str
    bounding_box: BoundingBox
    renderer: Renderer
    labels: list[str] = []
    design: str = "bundled-grid"
    calibration_revision: str | None = None
    mask_edits: list[MaskEdit] = Field(default_factory=list, max_length=32)


class MultiplePreviewRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["multiple"] = "multiple"
    colour_coverage: Literal["exact", "subset"] = "exact"
    placements: list[Placement]
    renderer: Renderer
    labels: list[str] = []
    design: str = "bundled-grid"
    calibration_revision: str | None = None
    mask_edits: list[MaskEdit] = Field(default_factory=list, max_length=32)


class SinglePreviewRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["single"] = "single"
    colour: str | None = None
    artwork: str | None = None
    bounding_box: BoundingBox
    renderer: Renderer
    labels: list[str] = []
    design: str = "bundled-grid"
    calibration_revision: str | None = None
    mask_edits: list[MaskEdit] = Field(default_factory=list, max_length=32)


PreviewRequest = ColourMatrixPreviewRequest | MultiplePreviewRequest | SinglePreviewRequest
"""The endpoint validates the body against the target template's kind, not by
its shape."""


IssueSeverity = Literal["block", "warn", "info"]
"""`listing_validation.Severity` on the wire. ``info`` is shown quietly and
counted nowhere: `IssueCounts` counts the two a seller has to act on."""
IssueTab = Literal["variants", "pricing", "images", "details"]


class Issue(ApiModel):
    severity: IssueSeverity
    tab: IssueTab
    where: str
    message: str


class IssueCounts(ApiModel):
    block: int
    warn: int


class ListingSummary(ApiModel):
    name: str
    garment_profile: str
    design: str | None
    """The representative artwork's name, as
    `GET /api/listing-designs/{name}/thumbnail` takes it: the first non-null
    of ``default``, ``on-light``, ``on-dark``, never a colour's own design.
    ``None`` with no base file chosen."""
    colour_count: int
    status: ListingStatus
    issue_counts: IssueCounts
    etsy_listing_id: int | None = None
    printify_product_id: str | None = None
    gestures: list[ListingGesture] = []
    """Which buttons the listings table offers for this row, from the same
    facts as ``status``."""


class ResolvedPrice(ApiModel):
    size: str
    amount: str
    """Formatted as `Money` prints itself, e.g. ``"249 NOK"``."""


def always_sent_list() -> Any:
    """An empty-list default the server always sends. ``default_factory``
    keeps the mutable default off the class (S01), and the explicit schema
    default keeps OpenAPI, and so the generated client, from marking the field
    optional."""
    return Field(default_factory=list, json_schema_extra={"default": []})


def always_sent_dict() -> Any:
    """:func:`always_sent_list` for a mapping."""
    return Field(default_factory=dict, json_schema_extra={"default": {}})


class EditorTabFields(ApiModel):
    """What the listing editor's tabs read, computed the same way for a
    listing and a listing template, whose editor mounts those tabs unchanged."""

    resolved_prices: list[ResolvedPrice] = always_sent_list()
    garment_materials: list[str] | None = None
    """Fibre materials from the selected garment profile, read-only: a
    listing never stores them."""
    garment_product_type: str | None = None
    garment_brand: str | None = None
    garment_model: str | None = None
    description_composed: str = ""


class ListingDetail(EditorTabFields, Listing):
    """The full `Listing`, plus what the editor needs and nothing a listing
    itself would ever store: computed status, computed issues, and (only
    meaningful right after a PATCH) which fields a rejected candidate failed
    on."""

    name: str
    modified_at: datetime | None
    """UTC modification time of ``listing.yaml``; ``None`` for an unsaved
    draft."""
    status: ListingStatus
    issues: list[Issue]
    field_errors: dict[str, str] = always_sent_dict()
    """Set only when a PATCH's candidate failed validation: nothing was
    written, and every other field describes the listing as it was. Empty on
    every GET and every successful PATCH."""
    gestures: list[ListingGesture] = always_sent_list()
    """The lifecycle actions the editor's action row offers, by the listings
    table's rule; empty for the unsaved draft."""
    etsy_listing_id: int | None = None
    printify_product_id: str | None = None
    pricing_plan_name: str | None = None
    """The resolved plan's filename stem, for display."""
    description_composed: str = ""
    """The final `etsy.description` text, as `Workspace.compose_description`
    joins it: what the Details tab's preview renders. The lead alone when
    ``ref`` does not resolve; an issue says why."""
    design_content_hash: str | None = None
    """Hash of the selected design refs and bytes, for AI proposal
    staleness; an unreadable file hashes as a stable marker. ``None`` only with
    no design."""


class GarmentProfileSummary(ApiModel):
    name: str
    sizes: list[str]
    materials: list[str] | None = None
    colors: dict[str, Literal["light", "dark"]]
    preview_template: str | None = None
    """The ``colour-matrix`` template the Variants tab judges colours on;
    ``None`` when the garment profile names none."""


class PricingPlanSummary(ApiModel):
    name: str
    garment_profile: str
    compatible: bool
    """Whether this plan declares the exact garment profile asked for."""
    ref: str
    """Workspace-rooted, ready to PATCH into ``pricing_plan:`` unchanged."""


class ListingDesignSummary(ApiModel):
    name: str
    file: str
    """Workspace-relative path under ``designs/``, e.g.
    ``designs/take-a-hike.png``."""


class MediaFileSummary(ApiModel):
    """One file a listing can put in `media:` as a file ref: a
    shared one under ``common-media/``, or one of the listing's own. A bare
    file uploaded as-is, rather than a rendered mockup."""

    name: str
    """Its path under ``common-media/`` or the listing's own directory: what
    the picture endpoints take."""
    file: str
    """Workspace-relative, for display, e.g.
    ``listings/take-a-hike/close-up.mp4``."""
    ref: str
    """The ref to write into ``media:`` unchanged: a shared file's
    workspace-relative path, or ``./close-up.mp4`` for a listing's own."""
    kind: MediaKind


class CommonCopySummary(ApiModel):
    """One `common-copy/*.md` file, for the Description tab's body-source
    selector. ``ref`` is workspace-relative, exactly what `description.ref`
    stores."""

    ref: str
    title: str
    """The file's front-matter title."""
    summary: str | None = None
    """The file's front-matter summary, if it has one."""


class EtsySectionSummary(ApiModel):
    """One row for the Details tab's Section dropdown.

    Existing rows come from the unscoped `EtsyShopClient.shop_sections`;
    creating one returns the same shape through the signed-in client.
    """

    id: int
    title: str


class EtsySectionsResponse(ApiModel):
    """The section picker's rows and whether Etsy could supply them.

    ``available`` distinguishes a configured shop with no sections -- where
    the editor can create the first one -- from a workspace that must retain
    the plain-text fallback because its Etsy connection is unavailable.
    """

    available: bool
    sections: list[EtsySectionSummary]


class CreateEtsySectionRequest(ApiModel):
    """The title Etsy should give a newly created shop section."""

    title: str = Field(min_length=1)

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class WorkspaceSummary(ApiModel):
    """Which workspace the UI is pointed at. One workspace is one shop, so the
    sidebar names it -- the difference between a test shop and the real one is
    worth seeing before an edit, not after an apply."""

    shop_name: str | None
    """``etsy.shop_name`` from ``shop.yaml``; ``None`` until ``setup`` reads
    it back from Etsy."""
    storage_id: str
    """Opaque identity of the workspace root, for browser storage keys: two
    roots never share one, even with the same shop name."""


class DraftListingRequest(ApiModel):
    """A candidate ``listing.yaml``, as the editor holds it before the listing
    exists.

    ``dict`` rather than ``Listing``, deliberately: an incomplete candidate is
    the *normal* case on this endpoint, and rejecting it at the FastAPI boundary
    would answer with a 422 the editor cannot render. The point is to describe
    it as it stands and report what is missing."""

    document: dict[str, Any] = Field(default_factory=dict)


class CreateListingRequest(ApiModel):
    """The whole document the editor built, written as edited -- not a
    handful of fields to build one from."""

    name: str
    document: dict[str, Any]


class RenameListingRequest(ApiModel):
    new_name: str


class TemplateRenameResponse(ApiModel):
    """A mockup template's rename. ``updated`` and ``unresolved`` are
    workspace-relative files: those now naming it, and those that could not be
    read or written and may still name the old one."""

    name: str
    updated: list[str]
    unresolved: list[str]


class PixelSize(ApiModel):
    width: int
    height: int


class ListingTemplateSummary(ApiModel):
    """One card on the Listing templates page."""

    name: str
    garment: str
    """The garment profile's blueprint as a seller names it
    (``Comfort Colors 1717``), or the profile's own name when it will not
    load."""
    colour_count: int
    pricing_plan_name: str | None
    """The plan ref's filename stem; ``None`` when the template prices its
    sizes itself."""
    media: list[MediaEntry]
    batch_count: int = 0
    """Batches made from this template, while their records last."""
    design_minimum: PixelSize | None = None
    """The smallest design the garment's print area takes; ``None`` when the
    garment profile will not load."""


class ListingTemplateSource(ApiModel):
    kind: Literal["listing", "listing-template"]
    name: str


class ListingTemplateAsset(ApiModel):
    """A file the draft will copy: the ``./`` ref the template will name it
    by, and the ref it has in its source -- which is where the *name it*
    page's thumbnail has to come from, since the copy does not exist yet."""

    ref: str
    source_ref: str


class ListingTemplateDetail(EditorTabFields, ListingTemplate):
    """A listing template as its pages read it, saved or not -- one shape for
    both, as `ListingDetail` is one shape for a listing and the unnamed draft.

    A draft (``GET /draft``: Save as listing template or Clone, written
    nowhere) has ``name`` ``""``, no ``modified_at``, and says
    where it came from in ``source`` and ``assets``."""

    name: str
    modified_at: datetime | None
    issues: list[Issue]
    garment: str | None = None
    pricing_plan_name: str | None = None
    source: ListingTemplateSource | None = None
    assets: list[ListingTemplateAsset] = always_sent_list()
    description_composed: str = ""
    """The body alone: a template has no lead, and each listing's own is
    placed above it."""


class ListingTemplateSaveResult(ApiModel):
    """What a create or ``PUT`` did. Refusing an incomplete document is
    a 200 with ``saved: false``, as a listing's malformed PATCH is, because the
    editor shows the issues and keeps going; nothing was written."""

    saved: bool
    issues: list[Issue]
    field_errors: dict[str, str] = {}
    template: ListingTemplateDetail | None = None


class CreateListingTemplateRequest(ApiModel):
    """Save as listing template (``from_listing``) or Clone
    (``from_template``) -- exactly one. There is no blank creation."""

    name: str
    from_listing: str | None = None
    from_template: str | None = None
    document: dict[str, Any] | None = None
    """The seller's edits made before naming it, as ``template.yaml`` would
    hold them; absent means the draft as the source gives it. Checked as a ``PUT`` is,
    and its ``./`` refs must be files the draft copies."""

    @model_validator(mode="after")
    def _exactly_one_source(self) -> CreateListingTemplateRequest:
        if (self.from_listing is None) == (self.from_template is None):
            raise ValueError("give exactly one of from_listing and from_template")
        return self


class StagingRowDetail(ApiModel):
    """One unique design on the staging page."""

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
    will name instead of writing its own."""


class StagingDetail(ApiModel):
    id: str
    listing_template: str
    label: str
    template_saved_at: datetime
    """When the frozen listing template was last saved."""
    expires_at: datetime
    rows: list[StagingRowDetail]
    ignored: list[str]
    """A ZIP's files that are not PNGs, by their path in it."""
    ai_blocked: AiReadinessBlock | None = None
    """Set only while a prompt, a ready provider or Etsy market access is
    missing, which refuses Create; nothing is said when AI can run."""


class StagingRefusal(ApiModel):
    """A ``422``'s ``detail`` for an upload refused before staging."""

    message: str
    remedy: str


class StagingPatch(ApiModel):
    """Every staging edit, applied in order: label, names, removals."""

    label: str | None = None
    names: dict[str, str] = {}
    remove: list[str] = []


class BatchRowDetail(ApiModel):
    id: str
    sources: list[str]
    name: str
    """The name actually created, which confirm may have suffixed."""
    design: str
    creation: Literal["pending", "created", "failed"]
    error: str | None
    ai: AiState | None = None
    """The row's AI work; ``None`` until its listing exists."""
    ai_steps: list[WorkflowStep] = []
    """The live run's nodes while running, else the last run's as it ended."""
    ai_error: str | None = None
    queue_position: int | None = None
    """1 for the next row to start, across every batch; ``None`` unless
    queued."""
    waiting_for_backup: bool = False
    """Held by a backup's pause: accepted and queued, starting once the backup
    step ends. Never stored."""
    proposal: Literal["ready", "stale", "resolved"] | None = None
    """The listing's cached proposal: sections waiting and current,
    waiting but out of date, or every section dealt with."""
    stale_reasons: list[str] = []
    reviewed: bool = False
    """The seller's own judgement."""
    reviewable: bool = False
    """Whether Mark reviewed is offered: not on a queued, drafting, deleted
    or never-created row."""
    deleted: bool = False
    """The listing was deleted; the row stays, struck through."""
    deployable: bool = False
    """Whether Deploy reviewed takes this row: reviewed, with changes its
    last apply did not deploy."""


BatchStatus = Literal["staging", "drafting", "in_review", "complete", "stopped"]
"""Recent batches' derived status: ``staging`` for a session not
confirmed yet, the rest `batches.standing`'s."""


class BatchDetail(ApiModel):
    id: str
    label: str
    listing_template: str
    created_at: datetime
    rows: list[BatchRowDetail]
    concurrency: int = 1
    """``batch_ai.concurrency``: how many rows draft at once."""
    status: BatchStatus = "drafting"


class BatchPatch(ApiModel):
    """Rename the batch: its label only, never its identity."""

    label: str


class ReviewedRequest(ApiModel):
    reviewed: bool


class BatchIndexEntry(ApiModel):
    """One row of Recent batches: a confirmed batch, or a staging
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


class ListingBatch(ApiModel):
    """The batch a listing was made by, for the editor's row above the head:
    Back to batch and Mark reviewed."""

    batch_id: str
    label: str
    row_id: str
    reviewed: bool
    reviewable: bool


class _CreateRunRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    publish: bool = False
    """Publish new and still-draft listings on Etsy rather than leave drafts.
    Off unless asked; an apply must repeat what its reviewed plan chose."""


class ListingPlanRequest(_CreateRunRequest):
    kind: Literal["plan"]
    scope: Literal["listings"]
    listings: list[str] = Field(min_length=1)


class WorkspacePlanRequest(_CreateRunRequest):
    kind: Literal["plan"]
    scope: Literal["workspace"]


class BatchPlanRequest(_CreateRunRequest):
    """Plan the reviewed rows of one listing batch that have changes to
    deploy; the server resolves which."""

    kind: Literal["plan"]
    scope: Literal["batch"]
    batch_id: str


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


class BatchApplyRequest(_CreateRunRequest):
    kind: Literal["apply"]
    scope: Literal["batch"]
    batch_id: str
    listings: list[str]
    expect: dict[str, str]
    reviewed_run_id: str


CreateRunRequest = (
    ListingPlanRequest
    | WorkspacePlanRequest
    | BatchPlanRequest
    | ListingApplyRequest
    | WorkspaceApplyRequest
    | BatchApplyRequest
)


class _RunSummary(ApiModel):
    id: str
    scope: RunScope
    batch_id: str | None = None
    """The listing batch a ``batch``-scoped run deploys."""
    listings: list[str]
    seen: bool
    reviewed_run_id: str | None
    created_at: datetime
    publish: bool = False
    """Whether this run publishes new and still-draft listings."""
    waiting_for_backup: bool = False
    """Held by a backup's pause: accepted and queued, starting once the backup
    step ends. Never stored."""


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
    """Every event this run has produced so far, in order: what a client
    reattaching to the run replays."""


class ApplyRunDetail(ApplyRunSummary):
    events: list[RunEvent]


RunDetail = Annotated[PlanRunDetail | ApplyRunDetail, Field(discriminator="kind")]


class SeoReadinessResponse(ApiModel):
    """Whether AI Mode can be enabled for one saved listing right now. The
    frontend leaves the control visible and disabled when ``ready`` is false;
    ``reason`` explains why to a developer or support reader."""

    ready: bool
    reason: str | None = None
    batch_pending: bool = False
    """A batch row owns this listing's AI: the editor follows the
    batch run instead of offering its own."""
    deploying: bool = False
    """A UI plan or apply holds this listing: the editor asks again
    until the deploy lets it go."""


class ProposalResolutionPatch(ApiModel):
    """``PATCH /api/listings/{name}/proposal/resolution``: the sections to
    record, on the proposal generated at ``generated_at`` -- a regeneration
    that landed meanwhile is a different proposal, and is a 412. ``pending``
    reopens a section."""

    generated_at: datetime
    title: Resolution | None = None
    tags: Resolution | None = None
    lead: Resolution | None = None


class CreateAiRunRequest(ApiModel):
    listing: str
    draft_brief: bool = False
    """Draft the brief first. Only honoured while the saved brief is empty;
    a run whose listing already has one skips the Brief node."""


class AiRunRefusal(ApiModel):
    """A ``409`` from ``POST /api/ai/runs``: exactly one of the two is set.
    ``active_run`` names the run to reattach to; ``reason`` says which
    readiness rule failed."""

    active_run: str | None = None
    reason: str | None = None


class AiRunSummary(ApiModel):
    id: str
    listing: str
    draft_brief: bool
    origin: Literal["manual", "batch"]
    phase: AiRunPhase
    steps: list[WorkflowStep]
    created_at: datetime
    started_at: datetime | None
    """When the run began working: ``created_at``, or later when a backup's
    pause held it; ``None`` while it is held."""
    finished_at: datetime | None
    waiting_for_backup: bool = False
    """Held by a backup's pause: accepted and queued, starting once the backup
    step ends. Never stored."""


class AiRunDetail(AiRunSummary):
    events: list[AiRunEvent]


class CalibrationSaveRequest(ApiModel):
    """A single recoverable calibration transaction."""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=256)
    config: TemplateConfig
    mask_edits: list[MaskEdit] = Field(default_factory=list, max_length=256)


class MapReadinessResponse(ApiModel):
    state: Literal["needs_preparation", "out_of_date", "ready", "not_required"]
    reason: str | None = None
    message: str | None = None
    content_digest: str | None = None
    can_render: bool


class PreparationPlacementResponse(ApiModel):
    placement_id: str | None
    mask_available: bool
    mask_reason: str | None
    undo_count: int


class PreparationJobResponse(ApiModel):
    config_revision: str
    id: str
    template: str
    kind: Literal["prepare", "rebuild", "coverage"]
    phase: Phase
    step: str
    elapsed: float
    placements_completed: int
    placements_total: int
    error: str | None
    last_event_sequence: int
    queue_position: int | None
    engine_version: str | None
    waiting_for_backup: bool = False
    """Held by a backup's pause: accepted and queued, starting once the backup
    step ends. Never stored."""


class PreparationResponse(ApiModel):
    template: str
    config_revision: str
    main_photo: str
    maps: MapReadinessResponse
    placements: list[PreparationPlacementResponse]
    active_job: PreparationJobResponse | None
    latest_job: PreparationJobResponse | None
    renderer_settings: dict[str, Any]
    prepared_engine: str | None


class PositionReadinessResponse(ApiModel):
    ready: bool
    preparing: bool


class CreatePreparationRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")
    template: str
    config_revision: str
    request_id: str = Field(min_length=1, max_length=256)
    action: Action = "prepare"
    previous_job: str | None = None
    reset_masks_for_photo: bool = False


class MaskHistoryStroke(ApiModel):
    before: str
    operation: Stroke


class MaskHistoryResponse(ApiModel):
    checksum: str
    undo_count: int
    strokes: list[MaskHistoryStroke]


class MarigoldRuntimeResponse(ApiModel):
    available: bool
    problem: str | None
    engine_version: str | None
    required_engine: str
    installation_id: str | None
    update_available: bool
    max_num_inference_steps: int
    max_ensemble_size: int
    max_image_dimension: int


class PreparationResyncResponse(ApiModel):
    resync: Literal[True] = True


class ReturnPolicyTermsBody(ApiModel):
    """``etsy.listing_defaults.return_policy``: a policy by its terms."""

    accepts_returns: bool
    accepts_exchanges: bool
    within_days: int | None = None


class CurrencyOption(ApiModel):
    code: str
    name: str


class ShopListingDefaults(ApiModel):
    who_made: str
    when_made: str
    is_supply: bool
    production_partner: str | None
    shipping_profile: str | None
    return_policy: ReturnPolicyTermsBody | None
    renewal: str


class ShopSettingsResponse(ApiModel):
    revision: str
    """sha256 of the file's exact bytes; the next PATCH must send it."""
    currency: str
    supported_currencies: list[CurrencyOption]
    """Etsy Payments' currencies, in the order the page offers them."""
    listing_defaults: ShopListingDefaults
    preferred_print_provider: str | None


class ShopChanges(ApiModel):
    """Only the keys sent are changed; ``null`` removes an optional one.
    Values are loosely typed on purpose: the whole candidate document is
    validated by ``Defaults``, which names each refused field."""

    model_config = ConfigDict(extra="forbid")

    currency: str | None = None
    who_made: str | None = None
    when_made: str | None = None
    is_supply: bool | None = None
    production_partner: str | None = None
    shipping_profile: str | None = None
    return_policy: ReturnPolicyTermsBody | None = None
    renewal: str | None = None
    preferred_print_provider: str | None = None


class ShopPatchRequest(ApiModel):
    revision: str
    changes: ShopChanges


class ShopSaveRefusal(ApiModel):
    """A 412 (``stale``: reload, then edit again) or a 422 (``invalid``:
    each refused dotted shop.yaml key to its reason). Nothing was written."""

    kind: Literal["stale", "invalid"]
    message: str
    field_errors: dict[str, str] = Field(default_factory=dict)


class WorkspaceSettingsResponse(ApiModel):
    revision: str
    template_positions: TemplatePositionLimits
    """Current limits, including defaults."""
    concurrency: int
    weights: dict[str, float]
    """Relative weights, normalized only for display by the page."""
    default_weights: dict[str, int]
    providers: list[AiProviderSettings]
    step_limit_minutes: int
    run_limit_minutes: int
    """At least ``max(5, enabled providers x step_limit_minutes)``; the page
    computes that floor from ``providers`` as the seller edits."""
    backup: BackupSettings | None = None
    """The ``backup:`` block; ``None`` while backups are off."""


class WorkspaceSettingsChanges(ApiModel):
    model_config = ConfigDict(extra="forbid")

    concurrency: int | float | None = None
    weights: dict[str, int | float] | None = None
    providers: list[dict[str, Any]] | None = None
    step_limit_minutes: int | float | None = None
    run_limit_minutes: int | float | None = None
    template_positions: dict[str, Any] | None = None
    """The whole limits section; only the leaves it changes are written."""
    backup_destinations: list[str] | None = None
    """Backup's Setup page: every destination, in order. A new one is
    created, inside a folder that must exist."""
    backup_interval_hours: int | None = None
    backup_retention: dict[str, Any] | None = None


class WorkspaceSettingsPatch(ApiModel):
    revision: str
    changes: WorkspaceSettingsChanges


class SettingsSaveRefusal(ApiModel):
    kind: Literal["stale", "invalid"]
    """``stale`` (412): settings.yaml changed since the page read it, so
    reload; ``invalid`` (422): ``field_errors`` say what to change."""
    message: str
    field_errors: dict[str, str] = Field(default_factory=dict)


class BackupRefusal(ApiModel):
    """Set-up's, create's and connect's refusals."""

    kind: Literal["stale", "conflict", "invalid"]
    """As a settings save's, plus ``conflict`` (409): a folder that holds
    files or a repository's copy."""
    message: str
    field_errors: dict[str, str] = Field(default_factory=dict)

    connect_from: str | None = None
    """Create refused because this destination holds a repository's copy:
    connect it instead."""


class TemplatePositionImpactRequest(ApiModel):
    limits: dict[str, Any]
    """Candidate limits, shaped as ``template_positions`` in settings.yaml."""


class ListingOutsideBody(ApiModel):
    listing: str
    positions: list[str]
    """Dotted ``template_positions`` keys the candidate limits would refuse."""


class TemplatePositionImpactResponse(ApiModel):
    """What saving the candidate limits would change; nothing is written."""

    outside: list[ListingOutsideBody]
    templates_needing_inference: list[str]
    """Marigold templates whose preparation evidence would need model inference
    to cover the wider limits."""


class ConnectionRowBody(ApiModel):
    state: Literal["connected", "not_connected", "lookup_failed"]
    shop_name: str | None
    shop_id: int | None
    commands: list[str]
    """What to run in a terminal, in order, when ``not_connected``."""
    problem: str | None
    signed_in_user_id: int | None
    sales_channel: str | None
    shop_currency: str | None
    """The live Etsy shop's own currency, when a lookup read it."""


class ShopConnectionsResponse(ApiModel):
    etsy: ConnectionRowBody
    printify: ConnectionRowBody


class ReturnPolicyChoiceBody(ApiModel):
    terms: ReturnPolicyTermsBody
    label: str


class EtsyLookupsBody(ApiModel):
    available: bool
    problem: str | None
    production_partners: list[str]
    shipping_profiles: list[str]
    return_policies: list[ReturnPolicyChoiceBody]


class PrintifyLookupsBody(ApiModel):
    available: bool
    problem: str | None
    print_providers: list[str]


class ShopLookupsResponse(ApiModel):
    etsy: EtsyLookupsBody
    printify: PrintifyLookupsBody


class BackupSetUpRequest(ApiModel):
    """The backup set-up form."""

    revision: str
    """``settings.yaml``'s revision from ``GET /api/admin/settings``."""
    repository: str
    destinations: list[str] = Field(default_factory=list)
    interval_hours: BackupIntervalHours = 12
    retention: RetentionSettings = Field(default_factory=RetentionSettings)
    password: str


class BackupConnected(ApiModel):
    """The backup set-up connected instead of creating one."""

    destination: str
    """The destination it was copied from."""
    snapshots: int
    notice: str | None = None
    """Set when its snapshots name several workspaces, so this workspace
    got a new workspace ID and starts its own retention."""


class BackupSetUpResponse(BackupOverview):
    """The status once set up, and what set-up connected, if anything."""

    connected: BackupConnected | None = None
    """Set when a destination already held a backup: set-up copied it to
    the backup storage folder and uses it, instead of creating one."""


class BackupNewRepositoryRequest(ApiModel):
    """Create a new repository while the configured one is missing."""

    revision: str
    """``settings.yaml``'s revision from ``GET /api/admin/settings``."""
    repository: str
    """The folder the seller confirmed: new or empty."""
    password: str | None = None
    """Only read when no password is stored."""


class BackupConnectRequest(ApiModel):
    """Connect an existing repository, such as a destination copy restored
    onto a new machine, by copying it to local disk first."""

    revision: str
    source: str
    """The repository to copy from; only read."""
    repository: str
    """The local folder to copy into: new or empty."""
    password: str | None = None
    """Only read when no password is stored."""


class BackupHistoryResponse(ApiModel):
    runs: list[HistoryEntry]
    """Newest first, failed runs included."""


class BackupSnapshot(ApiModel):
    id: str
    short_id: str
    time: datetime
    files: int | None = None
    size: int | None = None
    """Bytes the backup read."""
    restore_target: str
    """The restore dialog's suggested folder for it."""


class BackupSnapshotsResponse(ApiModel):
    workspace: str
    """The live workspace, which a restore refuses."""
    snapshots: list[BackupSnapshot]
    """Every snapshot restic lists, made by the app or by hand, newest first."""


class BackupRestoreRequest(ApiModel):
    snapshot: str
    """An id, its start, or ``latest``."""
    target: str
    """A new or empty folder, as a full path."""


class BackupRepairRequest(ApiModel):
    destination: str
    """As ``settings.yaml`` names it."""


class BackupRepairResponse(ApiModel):
    set_aside: str | None
    """``<destination>-set-aside-<date>``; ``None`` when nothing was moved."""
    moved: list[str]
    outcome: CopyOutcome
    """How the copy after it went."""
    message: str | None = None
