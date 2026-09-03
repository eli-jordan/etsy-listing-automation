import type { components } from "./api/schema";

export type WarpConfig = components["schemas"]["WarpConfig"];
export type DisplaceConfig = components["schemas"]["DisplaceConfig"];
export type ShadeConfig = components["schemas"]["ShadeConfig"];
export type TemplateSummary = components["schemas"]["TemplateSummary"];
export type ShadeBlend = ShadeConfig["blend"];

export type Point = [number, number];

/** Four corners, in template pixel space: top-left, top-right, bottom-right, bottom-left. */
export type Quad = WarpConfig["quad"];

export interface RenderConfigState {
  warp: WarpConfig;
  displace: DisplaceConfig;
  shade: ShadeConfig;
}
