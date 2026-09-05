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
  UploadResponse,
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
 * Returns null when the template has no template.yaml yet (a fresh upload).
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

/**
 * Multipart upload with a repeated `files` field -- built by hand rather than
 * through the generated client, since openapi-fetch's multipart support
 * doesn't cover repeated array fields cleanly.
 */
export async function uploadTemplate(name: string, files: File[]): Promise<UploadResponse> {
  const form = new FormData();
  for (const file of files) form.append("files", file);

  // No `kind`: it is asked afterwards, in the KindPicker, once the photos are
  // on screen. The server stores them under their own names until then.
  const response = await fetch(`/api/templates?${new URLSearchParams({ name })}`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) throw new CalibratorApiError(`upload failed for ${name}`);
  return (await response.json()) as UploadResponse;
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
export async function assignKind(
  name: string,
  kind: TemplateKind,
): Promise<TemplateConfigState> {
  const { data, error } = await api.POST("/api/templates/{name}/kind", {
    params: { path: { name } },
    body: { kind },
  });
  if (error) throw new CalibratorApiError(`could not set the kind for ${name}`);
  return data as unknown as TemplateConfigState;
}

/** The calibrator's test-design library: three bundled targets plus whatever
 * the user has uploaded into the workspace (A16). */
export async function listDesigns(): Promise<DesignSummary[]> {
  const { data, error } = await api.GET("/api/designs");
  if (error || !data) throw new CalibratorApiError("failed to list test designs");
  return data;
}

/** Adds a PNG to the library. Hand-rolled like `uploadTemplate` -- the
 * generated client cannot describe a multipart body. */
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
 */
export function templateThumbnailUrl(name: string): string {
  return `/api/templates/${encodeURIComponent(name)}/thumbnail`;
}

type PreviewBody =
  | { colour: string; bounding_box: BoundingBox; displace: DisplaceConfig; shade: ShadeConfig }
  | { placements: Placement[]; displace: DisplaceConfig; shade: ShadeConfig }
  | { bounding_box: BoundingBox; displace: DisplaceConfig; shade: ShadeConfig };

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
): Promise<string> {
  const response = await fetch(`/api/templates/${encodeURIComponent(name)}/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, design }),
  });
  if (!response.ok) {
    throw new CalibratorApiError(`preview failed for ${name}`);
  }
  return URL.createObjectURL(await response.blob());
}
