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
export type CreateListingRequest = components["schemas"]["CreateListingRequest"];
export type EtsySectionSummary = components["schemas"]["EtsySectionSummary"];
export type TemplateMediaEntry = components["schemas"]["TemplateMediaEntry"];
/** Either an explicit template reference, or a bare path string to a shared
 * asset under `common-media/` -- mirrors `config/listing.py`'s `MediaEntry`. */
export type MediaEntry = TemplateMediaEntry | string;

// ── Deploy changes (A29-A33, docs/deploy-changes.md) ────────────────────────

export type RunKind = components["schemas"]["CreateRunRequest"]["kind"];
export type RunPhase = components["schemas"]["RunSummary"]["phase"];
export type RunSummary = components["schemas"]["RunSummary"];
export type RunDetail = components["schemas"]["RunDetail"];
export type CreateRunRequest = components["schemas"]["CreateRunRequest"];
export type RunEvent = RunDetail["events"][number];

export type ActionDTO = components["schemas"]["ActionDTO"];
export type DriftDTO = components["schemas"]["DriftDTO"];
export type FieldChangeDTO = components["schemas"]["FieldChangeDTO"];
export type ListChangeDTO = components["schemas"]["ListChangeDTO"];
export type PriceChangeDTO = components["schemas"]["PriceChangeDTO"];
export type MediaChangeDTO = components["schemas"]["MediaChangeDTO"];
export type ChangeDTO = FieldChangeDTO | ListChangeDTO | PriceChangeDTO | MediaChangeDTO;
export type StagePlanDTO = components["schemas"]["StagePlanDTO"];
export type PlanDTO = components["schemas"]["PlanDTO"];

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

/** `engine/stages/render.py`'s `RenderSnapshot`, as it crosses the wire inside
 * `StagePlanDTO.snapshot` (an untyped `dict` there -- `render`'s own stage is
 * the only thing that knows this shape, same rule as the backend's DTO
 * module: "the frontend already has to know one stage's snapshot shape from
 * another"). */
export interface RenderSceneSnapshot {
  scene: string;
  template: string;
  colour: string | null;
  state: "cached" | "stale" | "missing";
  preview: boolean;
}
export interface RenderSnapshot {
  scenes: RenderSceneSnapshot[];
}

/** `engine/stages/printify_product.py`'s `ProductSnapshot`. `price` is a
 * `Money` rendered as `"349 NOK"` (see `ui/runs/events.py`'s `_jsonable`). */
export interface ProductVariantSnapshot {
  size: string;
  colour: string;
  price: string;
}
export interface ProductSnapshot {
  desired: ProductVariantSnapshot[];
  live: ProductVariantSnapshot[];
}

/** `engine/stages/publish.py`'s `PublishSnapshot`. */
export interface BelowCostRow {
  size: string;
  colour: string;
  price: string;
  cost: string;
}
export interface PublishSnapshot {
  below_cost: BelowCostRow[];
}

/** `engine/stages/etsy_listing.py`'s `EtsyListingSnapshot`/`EtsyListingFacts`. */
export interface EtsyListingFacts {
  title: string | null;
  tags: string[];
  shop_section: string | null;
  shipping_profile: string | null;
}
export interface EtsyListingSnapshot {
  desired: EtsyListingFacts;
  live: EtsyListingFacts | null;
}

/** `engine/stages/etsy_media.py`'s `EtsyMediaSnapshot`. */
export interface DesiredImageSnapshot {
  rank: number;
  ref: string;
  file: string;
}
export interface LiveImageSnapshot {
  rank: number | null;
  ref: string | null;
  image_id: number;
  url: string | null;
}
export interface EtsyMediaSnapshot {
  desired: DesiredImageSnapshot[];
  live: LiveImageSnapshot[];
}
