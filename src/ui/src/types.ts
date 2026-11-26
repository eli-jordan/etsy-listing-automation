import type { components } from "./api/schema";

export type Point = components["schemas"]["Point"];
export type BoundingBox = [Point, Point, Point, Point];

/** A template photo's true pixel size, the space every box in template.yaml is
 * written in. From the API, never measured off the editor's downscaled image.
 * `null` where it is optional: no readable photo, so nothing to calibrate. */
export type PhotoSpace = [width: number, height: number];

export type DisplaceConfig = components["schemas"]["DisplaceConfig"];
export type ShadeConfig = components["schemas"]["ShadeConfig"];
export type ShadeBlend = ShadeConfig["blend"];

export type Placement = components["schemas"]["Placement"];

/** `Listing.design`: reserved base keys and colour keys, each a ref. Only
 * `on-light`/`on-dark` may be `null` -- a slot not filled yet (ADR-0053). */
export type DesignMap = Record<string, string | null>;

export type TemplateKind = "colour-matrix" | "multiple" | "single";
export type DesignSummary = components["schemas"]["DesignSummary"];

export type ColourReportRow = components["schemas"]["ColourReportRow"];

export type ColourMatrixTemplate = components["schemas"]["ColourMatrixTemplate"];
export type MultipleTemplate = components["schemas"]["MultipleTemplate"];
export type SingleTemplate = components["schemas"]["SingleTemplate"];

export type TemplateConfigState = ColourMatrixTemplate | MultipleTemplate | SingleTemplate;

export type TemplateSummary = components["schemas"]["TemplateSummary"];
export type TemplatePhoto = components["schemas"]["TemplatePhoto"];

export type SeoReadinessResponse = components["schemas"]["SeoReadinessResponse"];
export type ListingProposal = components["schemas"]["ListingProposal"];
export type ProposalChoices = components["schemas"]["ProposalChoices"];
export type ProposalResolution = components["schemas"]["ProposalResolution"];
export type ProposalResolutionPatch = components["schemas"]["ProposalResolutionPatch"];
export type SeoProposalSnapshot = components["schemas"]["SeoProposalSnapshot"];
export type SeoRationaleEntry = components["schemas"]["SeoRationaleEntry"];
export type SeoWarningEntry = components["schemas"]["SeoWarningEntry"];

export type AiRunSummary = components["schemas"]["AiRunSummary"];
export type AiRunDetail = components["schemas"]["AiRunDetail"];
export type AiRunPhase = AiRunSummary["phase"];
export type AiRunEvent = AiRunDetail["events"][number];
export type WorkflowStep = components["schemas"]["WorkflowStep"];
export type MarketSnapshot = components["schemas"]["MarketSnapshot"];
export type ScoredListing = components["schemas"]["ScoredListing"];
export type PhraseScore = components["schemas"]["PhraseScore"];

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
export type MediaEntry = TemplateMediaEntry | string;

export type ListingTemplateSummary = components["schemas"]["ListingTemplateSummary"];
export type ListingTemplateDetail = components["schemas"]["ListingTemplateDetail"];
export type ListingTemplateSource = components["schemas"]["ListingTemplateSource"];
export type ListingTemplateSaveResult = components["schemas"]["ListingTemplateSaveResult"];

export type RunSummary =
  components["schemas"]["PlanRunSummary"] | components["schemas"]["ApplyRunSummary"];
export type RunDetail =
  components["schemas"]["PlanRunDetail"] | components["schemas"]["ApplyRunDetail"];
export type RunKind = RunSummary["kind"];
export type RunPhase = RunSummary["phase"];
export type CreateRunRequest =
  | components["schemas"]["ListingPlanRequest"]
  | components["schemas"]["WorkspacePlanRequest"]
  | components["schemas"]["BatchPlanRequest"]
  | components["schemas"]["ListingApplyRequest"]
  | components["schemas"]["WorkspaceApplyRequest"]
  | components["schemas"]["BatchApplyRequest"];
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

export const STAGE_LABELS: Record<string, string> = {
  render: "Render mockups",
  printify_product: "Printify product",
  publish: "Publish to Etsy",
  etsy_listing: "Etsy listing",
  etsy_media: "Etsy media",
  etsy_videos: "Etsy videos",
  retract: "Remove from Etsy",
  etsy_activate: "Go live on Etsy",
};

export type RenderSceneSnapshot = components["schemas"]["RenderSceneSnapshot"];
export type RenderSnapshot = components["schemas"]["RenderSnapshot"];

export type ProductVariantSnapshot = components["schemas"]["ProductVariantSnapshot"];
export type ProductSnapshot = components["schemas"]["ProductSnapshot"];

export type BelowCostRow = components["schemas"]["BelowCostRow"];
export type PublishSnapshot = components["schemas"]["PublishSnapshot"];

export type EtsyListingFacts = components["schemas"]["EtsyListingFacts"];
export type EtsyListingSnapshot = components["schemas"]["EtsyListingSnapshot"];

export type DesiredImageSnapshot = components["schemas"]["DesiredImageSnapshot"];
export type LiveImageSnapshot = components["schemas"]["LiveImageSnapshot"];
export type EtsyMediaSnapshot = components["schemas"]["EtsyMediaSnapshot"];

export type DesiredVideoSnapshot = components["schemas"]["DesiredVideoSnapshot"];
export type LiveVideoSnapshot = components["schemas"]["LiveVideoSnapshot"];
export type EtsyVideosSnapshot = components["schemas"]["EtsyVideosSnapshot"];

export type PhotoWarpRenderer = components["schemas"]["PhotoWarpRenderer"];
export type PhotoWarpTemplate<T> = Omit<T, "renderer"> & { renderer: PhotoWarpRenderer };

export type Renderer =
  components["schemas"]["PhotoWarpRenderer"] | components["schemas"]["MarigoldRenderer"];
