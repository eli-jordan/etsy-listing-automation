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

// ── Listings UI (phase 5) ──────────────────────────────────────────────────

export type Issue = components["schemas"]["Issue"];
export type IssueTab = Issue["tab"];
export type ListingSummary = components["schemas"]["ListingSummary"];
export type ListingDetail = components["schemas"]["ListingDetail"];
export type ListingStatus = ListingSummary["status"];
export type GarmentProfileSummary = components["schemas"]["GarmentProfileSummary"];
export type PricingPlanSummary = components["schemas"]["PricingPlanSummary"];
export type ListingDesignSummary = components["schemas"]["ListingDesignSummary"];
export type CreateListingRequest = components["schemas"]["CreateListingRequest"];
export type TemplateMediaEntry = components["schemas"]["TemplateMediaEntry"];
/** Either an explicit template reference, or a bare path string to a shared
 * asset under `common-media/` -- mirrors `config/listing.py`'s `MediaEntry`. */
export type MediaEntry = TemplateMediaEntry | string;
