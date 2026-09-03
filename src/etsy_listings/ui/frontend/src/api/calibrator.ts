import { api } from "./client";
import type {
  BoundingBox,
  BundledDesign,
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
export async function uploadTemplate(
  name: string,
  kind: TemplateKind,
  files: File[],
): Promise<UploadResponse> {
  const form = new FormData();
  for (const file of files) form.append("files", file);

  const response = await fetch(`/api/templates?${new URLSearchParams({ name, kind })}`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) throw new CalibratorApiError(`upload failed for ${name}`);
  return (await response.json()) as UploadResponse;
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
  design: BundledDesign = "bundled-grid",
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
