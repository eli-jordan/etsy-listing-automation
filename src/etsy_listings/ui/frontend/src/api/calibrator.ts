import { api } from "./client";
import type {
  BoundingBox,
  ColourReportRow,
  DesignSummary,
  DisplaceConfig,
  Placement,
  ShadeConfig,
  TemplateConfigState,
  TemplateKind,
  TemplateSummary,
} from "../types";

/**
 * The calibrator's whole HTTP surface. Everything above this file works in
 * domain types and never touches fetch, URLs or the generated schema.
 */

export class CalibratorApiError extends Error {}

export async function listTemplates(): Promise<TemplateSummary[]> {
  const { data, error } = await api.GET("/api/templates");
  if (error) throw new CalibratorApiError("could not load templates");
  return data;
}

/**
 * Returns null when the template has no template.yaml yet -- a folder of
 * photos that has not been given a kind.
 *
 * The cast is because openapi-fetch widens `bounding_box`'s 4-tuple to a
 * plain array when inferring the response type of a 3-way discriminated
 * union -- the server still enforces exactly 4 points either way.
 */
export async function getTemplateConfig(name: string): Promise<TemplateConfigState | null> {
  const { data, error } = await api.GET("/api/templates/{name}/config", {
    params: { path: { name } },
  });
  if (error) return null;
  return data as unknown as TemplateConfigState;
}

export async function saveTemplateConfig(
  name: string,
  config: TemplateConfigState,
): Promise<TemplateConfigState> {
  const { data, error } = await api.PUT("/api/templates/{name}/config", {
    params: { path: { name } },
    body: config,
  });
  if (error) throw new CalibratorApiError("could not save template.yaml");
  return data as unknown as TemplateConfigState;
}

/** What each photo will be taken as if this becomes a colour-matrix set.
 * Reporting only -- PRD 7a makes the filename the source of truth. */
export async function getColourReport(name: string): Promise<ColourReportRow[]> {
  const { data, error } = await api.GET("/api/templates/{name}/colour-report", {
    params: { path: { name } },
  });
  if (error || !data) throw new CalibratorApiError(`could not read the colour report for ${name}`);
  return data;
}

/** The first calibration step. Writes the starting template.yaml for that
 * shape; refused if one already exists, since kind decides the whole file
 * shape (A11) and changing it would discard the old shape's calibration. */
export async function assignKind(name: string, kind: TemplateKind): Promise<TemplateConfigState> {
  const { data, error } = await api.POST("/api/templates/{name}/kind", {
    params: { path: { name } },
    body: { kind },
  });
  if (error) throw new CalibratorApiError(`could not set the kind for ${name}`);
  return data as unknown as TemplateConfigState;
}

/** The calibrator's test-design library: three bundled targets plus whatever
 * the user has uploaded into the workspace (A19). */
export async function listDesigns(): Promise<DesignSummary[]> {
  const { data, error } = await api.GET("/api/designs");
  if (error || !data) throw new CalibratorApiError("failed to list test designs");
  return data;
}

/** Adds a PNG to the library. Hand-rolled multipart -- the generated client
 * cannot describe one. */
export async function uploadDesign(file: File): Promise<DesignSummary> {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch("/api/designs", { method: "POST", body });
  if (!response.ok) {
    throw new CalibratorApiError("failed to upload test design");
  }
  return (await response.json()) as DesignSummary;
}

/**
 * The rail's per-template photo. A plain URL rather than a fetch: the browser
 * loads, caches and evicts these itself, and there is no object URL for anyone
 * to leak by forgetting to revoke it.
 *
 * `colour` narrows a `colour-matrix` set to one of its photos. Omit it for the
 * calibrator's rail, which is standing in for the whole template; pass it
 * anywhere a *particular* variant is on screen (the listings editor's reel and
 * its previews), or every colour of a set draws the same picture.
 */
export function templateThumbnailUrl(name: string, colour?: string | null): string {
  const base = `/api/templates/${encodeURIComponent(name)}/thumbnail`;
  return colour ? `${base}?colour=${encodeURIComponent(colour)}` : base;
}

/**
 * The same bare, inkless photo as {@link templateThumbnailUrl}, at its own
 * resolution rather than downscaled to list size. For the large preview
 * stages (the listing editor's Variants and Listing Images tabs) when there
 * is no design yet to composite -- {@link templateThumbnailUrl}'s 160px cap
 * is sized for a row of tiles, not a hero image.
 */
export function templatePhotoUrl(name: string, colour?: string | null): string {
  const base = `/api/templates/${encodeURIComponent(name)}/photo`;
  return colour ? `${base}?colour=${encodeURIComponent(colour)}` : base;
}

/**
 * A listing's real design, composited onto this template's *saved* geometry
 * -- unlike {@link templateThumbnailUrl}/{@link templatePhotoUrl}, which are
 * a bare, inkless photo, or {@link renderPreview}, which composites a
 * calibrator test design against *unsaved* geometry. A plain URL for the
 * same reason those are: the browser owns loading and caching it.
 */
export function templateDesignPreviewUrl(
  name: string,
  design: string,
  colour?: string | null,
): string {
  const params = new URLSearchParams({ design });
  if (colour) params.set("colour", colour);
  return `/api/templates/${encodeURIComponent(name)}/design-preview?${params.toString()}`;
}

/** A colour-matrix colour's real garment shade, sampled off its own scene
 * photo -- for a quick-glance swatch dot next to the colour's name. */
export async function getTemplateSwatch(name: string, colour: string): Promise<string> {
  const { data, error } = await api.GET("/api/templates/{name}/swatch", {
    params: { path: { name }, query: { colour } },
  });
  if (error || !data) throw new CalibratorApiError(`no swatch for ${name} colour ${colour}`);
  return data.hex;
}

type PreviewBody =
  | { colour: string; bounding_box: BoundingBox; displace: DisplaceConfig; shade: ShadeConfig }
  | { placements: Placement[]; displace: DisplaceConfig; shade: ShadeConfig }
  | { bounding_box: BoundingBox; displace: DisplaceConfig; shade: ShadeConfig };

/** Which of the server's two preview sizes to ask for.
 *
 * `editor` is the downscale the canvas drags against -- capped at a fixed
 * longest edge the server owns, and encoded as WebP, because a frame produced
 * five times a second is looked at once and thrown away. `full` is the photo's
 * own resolution as a PNG: the thing you approve.
 *
 * Boxes are in the template's true pixel space either way. A scaled preview
 * does not change the coordinates -- only how many pixels the server spends
 * drawing them.
 */
export type PreviewScale = "editor" | "full";

/**
 * Renders a preview through the real server-side pipeline. The body shape
 * must match the target template's actual kind -- the endpoint rejects a
 * mismatch rather than guessing. Returns an object URL the caller owns and
 * must revoke.
 */
export async function renderPreview(
  name: string,
  body: PreviewBody,
  design: string = "bundled-grid",
  scale: PreviewScale = "full",
): Promise<string> {
  const response = await fetch(
    `/api/templates/${encodeURIComponent(name)}/preview?scale=${scale}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...body, design }),
    },
  );
  if (!response.ok) {
    throw new CalibratorApiError(`preview failed for ${name}`);
  }
  return URL.createObjectURL(await response.blob());
}
