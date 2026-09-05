import type { components } from "./api/schema";

export type Point = components["schemas"]["Point"];
export type BoundingBox = [Point, Point, Point, Point];

export type DisplaceConfig = components["schemas"]["DisplaceConfig"];
export type ShadeConfig = components["schemas"]["ShadeConfig"];
export type ShadeBlend = ShadeConfig["blend"];

export type Placement = components["schemas"]["Placement"];

export type TemplateKind = "colour-matrix" | "multiple" | "single";
/** A16: the test design is an open library now, so a selection is an id
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
export type UploadResponse = components["schemas"]["UploadResponse"];
