import type { components } from "./api/schema";

export type Point = components["schemas"]["Point"];
export type BoundingBox = [Point, Point, Point, Point];

export type DisplaceConfig = components["schemas"]["DisplaceConfig"];
export type ShadeConfig = components["schemas"]["ShadeConfig"];
export type ShadeBlend = ShadeConfig["blend"];

export type Placement = components["schemas"]["Placement"];

export type TemplateKind = "colour-matrix" | "multiple" | "single";
/** A19: the test design is an open library now, so a selection is an id
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
 * through `Workspace.scene_photo`, not composed from PRD 7a's convention. */
export type TemplatePhoto = components["schemas"]["TemplatePhoto"];

// ── Listing SEO AI Mode (AI SEO implementation plan, PR7) ───────────────────

export type SeoReadinessResponse = components["schemas"]["SeoReadinessResponse"];
export type SeoProposalResponse = components["schemas"]["SeoProposalResponse"];
export type SeoProposalSnapshot = components["schemas"]["SeoProposalSnapshot"];
export type SeoRationaleEntry = components["schemas"]["SeoRationaleEntry"];
export type SeoWarningEntry = components["schemas"]["SeoWarningEntry"];

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
export type CommonMediaSummary = components["schemas"]["CommonMediaSummary"];
export type CommonCopySummary = components["schemas"]["CommonCopySummary"];
export type CreateListingRequest = components["schemas"]["CreateListingRequest"];
export type EtsySectionSummary = components["schemas"]["EtsySectionSummary"];
export type TemplateMediaEntry = components["schemas"]["TemplateMediaEntry"];
/** Either an explicit template reference, or a bare path string to a shared
 * asset under `common-media/` -- mirrors `config/listing.py`'s `MediaEntry`. */
export type MediaEntry = TemplateMediaEntry | string;

// ── Deploy changes (A29-A33, docs/deploy-changes.md) ────────────────────────

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
 * repeated here only for the display label lookup (`StepStrip.tsx`). */
export const STAGE_LABELS: Record<string, string> = {
  render: "Render mockups",
  printify_product: "Printify product",
  publish: "Publish to Etsy",
  etsy_listing: "Etsy listing",
  etsy_media: "Etsy images",
  retract: "Remove from Etsy",
};

/** Snapshot types generated from the stage-discriminated wire union. Narrow a
 * `StagePlanDTO` by `stage` and TypeScript narrows `snapshot` with it. */
export type RenderSceneSnapshot = components["schemas"]["RenderSceneSnapshot"];
export type RenderSnapshot = components["schemas"]["RenderSnapshot"];

/** `engine/stages/printify_product.py`'s `ProductSnapshot`. `price` is a
 * `Money` rendered as `"349 NOK"` (see `ui/runs/events.py`'s `_jsonable`). */
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
