import type { components } from "./api/schema";

export type Point = components["schemas"]["Point"];
export type BoundingBox = [Point, Point, Point, Point];

export type DisplaceConfig = components["schemas"]["DisplaceConfig"];
export type ShadeConfig = components["schemas"]["ShadeConfig"];
export type ShadeBlend = ShadeConfig["blend"];

export type Placement = components["schemas"]["Placement"];

/** `Listing.design`: reserved base keys and colour keys, each a ref. Only
 * `on-light`/`on-dark` may be `null` -- a slot not filled yet (ADR-0053). */
export type DesignMap = Record<string, string | null>;

export type TemplateKind = "colour-matrix" | "multiple" | "single";
/** the calibration-design library: the test design is an open library now, so a selection is an id
 * string, not a closed union -- the bundled targets keep their ids, an upload
 * uses its filename stem. */
export type DesignSummary = components["schemas"]["DesignSummary"];

export type ColourReportRow = components["schemas"]["ColourReportRow"];

export type ColourMatrixTemplate = components["schemas"]["ColourMatrixTemplate"];
export type MultipleTemplate = components["schemas"]["MultipleTemplate"];
export type SingleTemplate = components["schemas"]["SingleTemplate"];

/** A template.yaml is exactly one of these three shapes -- never a mix. */
export type TemplateConfigState = ColourMatrixTemplate | MultipleTemplate | SingleTemplate;

export type TemplateSummary = components["schemas"]["TemplateSummary"];
/** Where one of a template's scene photos really is -- resolved server-side
 * through `Workspace.scene_photo`, not composed from ADR-0004's convention. */
export type TemplatePhoto = components["schemas"]["TemplatePhoto"];

// ── Listing SEO AI Mode (AI SEO implementation plan, PR7) ───────────────────

export type SeoReadinessResponse = components["schemas"]["SeoReadinessResponse"];
/** A listing's cached proposal: the choices, their frozen inputs,
 * which sections the seller resolved, and whether the saved listing has
 * moved on since (`stale`, computed by the server). An AI run's `proposal`
 * event is the same shape plus its `type` and `seq`. */
export type ListingProposal = components["schemas"]["ListingProposal"];
export type ProposalChoices = components["schemas"]["ProposalChoices"];
export type ProposalResolution = components["schemas"]["ProposalResolution"];
export type ProposalResolutionPatch = components["schemas"]["ProposalResolutionPatch"];
export type SeoProposalSnapshot = components["schemas"]["SeoProposalSnapshot"];
export type SeoRationaleEntry = components["schemas"]["SeoRationaleEntry"];
export type SeoWarningEntry = components["schemas"]["SeoWarningEntry"];

// ── AI runs (features/market-seo-20260924/spec.md, *AI runs*; the implementation plan's Run contract) ─

export type AiRunSummary = components["schemas"]["AiRunSummary"];
export type AiRunDetail = components["schemas"]["AiRunDetail"];
export type AiRunPhase = AiRunSummary["phase"];
export type AiRunEvent = AiRunDetail["events"][number];
/** One node of the chain -- brief, market research, SEO suggestions -- as the
 * latest `step` event for it left it. */
export type WorkflowStep = components["schemas"]["WorkflowStep"];
export type MarketSnapshot = components["schemas"]["MarketSnapshot"];
export type ScoredListing = components["schemas"]["ScoredListing"];
export type PhraseScore = components["schemas"]["PhraseScore"];

// ── Listings UI (phase 5) ──────────────────────────────────────────────────

export type Issue = components["schemas"]["Issue"];
export type IssueTab = Issue["tab"];
export type ListingSummary = components["schemas"]["ListingSummary"];
export type ListingDetail = components["schemas"]["ListingDetail"];
export type ListingStatus = ListingSummary["status"];
export type GarmentProfileSummary = components["schemas"]["GarmentProfileSummary"];
export type PricingPlanSummary = components["schemas"]["PricingPlanSummary"];
export type ListingDesignSummary = components["schemas"]["ListingDesignSummary"];
export type WorkspaceSummary = components["schemas"]["WorkspaceSummary"];
export type MediaFileSummary = components["schemas"]["MediaFileSummary"];
export type CommonCopySummary = components["schemas"]["CommonCopySummary"];
export type CreateListingRequest = components["schemas"]["CreateListingRequest"];
export type EtsySectionSummary = components["schemas"]["EtsySectionSummary"];
export type EtsySectionsResponse = components["schemas"]["EtsySectionsResponse"];
export type TemplateMediaEntry = components["schemas"]["TemplateMediaEntry"];
/** Either an explicit template reference, or a bare path string to a shared
 * asset under `common-media/` -- mirrors `config/listing.py`'s `MediaEntry`. */
export type MediaEntry = TemplateMediaEntry | string;

// ── Listing templates (ADR-0047, template completeness) ────────────────────────────────────────────

export type ListingTemplateSummary = components["schemas"]["ListingTemplateSummary"];
export type ListingTemplateDetail = components["schemas"]["ListingTemplateDetail"];
/** A detail with `name` `""`: what Save as listing template or Clone would
 * write, written nowhere. `source` and `assets` say where it came from. */
export type ListingTemplateDraft = ListingTemplateDetail;
export type ListingTemplateSource = components["schemas"]["ListingTemplateSource"];
export type ListingTemplateSaveResult = components["schemas"]["ListingTemplateSaveResult"];

// ── Deploy changes (ADR-0037, ADR-0038, ADR-0039, ADR-0040, ADR-0041, docs/features/deploy-20260917/spec.md) ────────────────────────

export type RunSummary =
  components["schemas"]["PlanRunSummary"] | components["schemas"]["ApplyRunSummary"];
export type RunDetail =
  components["schemas"]["PlanRunDetail"] | components["schemas"]["ApplyRunDetail"];
export type RunKind = RunSummary["kind"];
export type RunPhase = RunSummary["phase"];
export type CreateRunRequest =
  | components["schemas"]["ListingPlanRequest"]
  | components["schemas"]["WorkspacePlanRequest"]
  | components["schemas"]["ListingApplyRequest"]
  | components["schemas"]["WorkspaceApplyRequest"];
export type RunEvent = RunDetail["events"][number];

export type ActionDTO = components["schemas"]["ActionDTO"];
export type DriftDTO = components["schemas"]["DriftDTO"];
export type FieldChangeDTO = components["schemas"]["FieldChangeDTO"];
export type ListChangeDTO = components["schemas"]["ListChangeDTO"];
export type PriceChangeDTO = components["schemas"]["PriceChangeDTO"];
export type MediaChangeDTO = components["schemas"]["MediaChangeDTO"];
export type ChangeDTO = FieldChangeDTO | ListChangeDTO | PriceChangeDTO | MediaChangeDTO;
export type PlanDTO = components["schemas"]["PlanDTO"];
export type StagePlanDTO = PlanDTO["stage_plans"][number];

export function stageWillRun(stage: StagePlanDTO): boolean {
  return stage.outcome.type === "work";
}

export function stageBlocked(stage: StagePlanDTO): string | null {
  return stage.outcome.type === "blocked" ? stage.outcome.message : null;
}

export function stageReason(stage: StagePlanDTO): string | null {
  return stage.outcome.type === "work" ? stage.outcome.reason : null;
}

export function stageChanges(stage: StagePlanDTO): ChangeDTO[] {
  return stage.outcome.type === "work" ? stage.outcome.changes : [];
}

export function stageActions(stage: StagePlanDTO): ActionDTO[] {
  return stage.outcome.type === "work" ? stage.outcome.actions : [];
}

/** One planned pipeline stage's own name, as `engine/stages/__init__.py`'s
 * `STAGES` orders them -- the order `PlanDTO.stage_plans` already arrives in,
 * repeated here only for the display label lookup (`StepStrip.tsx`).
 *
 * `etsy_media` is "Etsy media", not "Etsy images": `etsy_videos` is drawn
 * under it by the `group` the engine hands out, and each label
 * still reads on its own where there is no nesting, as in the batch view. */
export const STAGE_LABELS: Record<string, string> = {
  render: "Render mockups",
  printify_product: "Printify product",
  publish: "Publish to Etsy",
  etsy_listing: "Etsy listing",
  etsy_media: "Etsy media",
  etsy_videos: "Etsy videos",
  retract: "Remove from Etsy",
};

/** Snapshot types generated from the stage-discriminated wire union. Narrow a
 * `StagePlanDTO` by `stage` and TypeScript narrows `snapshot` with it. */
export type RenderSceneSnapshot = components["schemas"]["RenderSceneSnapshot"];
export type RenderSnapshot = components["schemas"]["RenderSnapshot"];

/** `engine/stages/printify_product.py`'s `ProductSnapshot`. `price` is a
 * `Money` rendered as `"349 NOK"` (see `core/application/deploy/events.py`'s `_jsonable`). */
export type ProductVariantSnapshot = components["schemas"]["ProductVariantSnapshot"];
export type ProductSnapshot = components["schemas"]["ProductSnapshot"];

/** `engine/stages/publish.py`'s `PublishSnapshot`. */
export type BelowCostRow = components["schemas"]["BelowCostRow"];
export type PublishSnapshot = components["schemas"]["PublishSnapshot"];

/** `engine/stages/etsy_listing.py`'s `EtsyListingSnapshot`/`EtsyListingFacts`. */
export type EtsyListingFacts = components["schemas"]["EtsyListingFacts"];
export type EtsyListingSnapshot = components["schemas"]["EtsyListingSnapshot"];

/** `engine/stages/etsy_media.py`'s `EtsyMediaSnapshot`. */
export type DesiredImageSnapshot = components["schemas"]["DesiredImageSnapshot"];
export type LiveImageSnapshot = components["schemas"]["LiveImageSnapshot"];
export type EtsyMediaSnapshot = components["schemas"]["EtsyMediaSnapshot"];

/** `engine/stages/etsy_videos.py`'s `EtsyVideosSnapshot`. */
export type DesiredVideoSnapshot = components["schemas"]["DesiredVideoSnapshot"];
export type LiveVideoSnapshot = components["schemas"]["LiveVideoSnapshot"];
export type EtsyVideosSnapshot = components["schemas"]["EtsyVideosSnapshot"];
