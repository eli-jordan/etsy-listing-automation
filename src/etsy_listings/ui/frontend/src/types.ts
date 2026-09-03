import type { components } from "./api/schema";

export type WarpConfig = components["schemas"]["WarpConfig"];
export type DisplaceConfig = components["schemas"]["DisplaceConfig"];
export type ShadeConfig = components["schemas"]["ShadeConfig"];
export type TemplateSummary = components["schemas"]["TemplateSummary"];
export type ShadeBlend = ShadeConfig["blend"];

export interface RenderConfigState {
  warp: WarpConfig;
  displace: DisplaceConfig;
  shade: ShadeConfig;
}

export type Point = [number, number];
