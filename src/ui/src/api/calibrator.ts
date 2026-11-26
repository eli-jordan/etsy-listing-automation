import type { MaskEdit } from "./preparation";
import { api, detailMessage, formBody, withTuples } from "./client";
import type { components } from "./schema";
import type {
  BoundingBox,
  ColourReportRow,
  DesignSummary,
  Renderer,
  Placement,
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

/** A template.yaml as read, with the revision a save must name in `If-Match`.
 *
 * `revision` is the bare revision id -- the same string preparation reports as
 * `config_revision` and a preview takes as `calibration_revision` -- not the
 * quoted ETag. Quoting is HTTP's business and stays in this file. `""` when
 * the server sent no ETag. */
export interface TemplateConfigDocument {
  config: TemplateConfigState;
  modifiedAt: string;
  revision: string;
}

/** A save the server refused because the file moved on since `revision`
 * was read (409 or 412): another tab, an external edit, or a preparation
 * that rewrote it. Only a reload resolves it. */
export class TemplateConflictError extends CalibratorApiError {
  constructor() {
    super("Template changed elsewhere. Reload before saving.");
  }
}

function revisionOf(response: Response | undefined): string {
  return (response?.headers.get("ETag") ?? "").replace(/^"|"$/g, "");
}

/** Null when the template has no template.yaml yet -- a folder of photos
 * that has not been given a kind. */
export async function getTemplateConfig(name: string): Promise<TemplateConfigDocument | null> {
  const { data, error, response } = await api.GET("/api/templates/{name}/config", {
    cache: "no-store",
    params: { path: { name } },
  });
  if (error) {
    // Only a 404 means no template.yaml yet. A template that needs repair or
    // will not parse has one, and must not be offered a kind.
    if (response.status === 404) return null;
    const fallback = `could not read the config for ${name}`;
    throw new CalibratorApiError(
      response.status === 409 ? detailMessage(error, fallback) : fallback,
    );
  }
  const modifiedAt = response.headers.get("Last-Modified");
  if (modifiedAt === null) throw new CalibratorApiError("template config has no modification time");
  return {
    config: withTuples<TemplateConfigState>(data),
    modifiedAt,
    revision: revisionOf(response),
  };
}

export interface SavedTemplateConfig {
  config: TemplateConfigState;
  revision: string;
}

export async function saveTemplateConfig(
  name: string,
  config: TemplateConfigState,
  maskEdits: MaskEdit[],
  revision: string,
): Promise<SavedTemplateConfig> {
  const { data, error, response } = await api.PUT("/api/templates/{name}/config", {
    params: { path: { name }, header: { "if-match": revision ? '"' + revision + '"' : "" } },
    body: { request_id: crypto.randomUUID(), config, mask_edits: maskEdits },
  });
  if (error) {
    if (response?.status === 409 || response?.status === 412) throw new TemplateConflictError();
    const fallback = "could not save template.yaml";
    throw new CalibratorApiError(
      response?.status === 422 ? detailMessage(error, fallback) : fallback,
    );
  }
  return { config: withTuples<TemplateConfigState>(data), revision: revisionOf(response) };
}

export type TemplateRenameResult = components["schemas"]["TemplateRenameResponse"];

export async function renameTemplate(name: string, newName: string): Promise<TemplateRenameResult> {
  const { data, error } = await api.POST("/api/templates/{name}/rename", {
    params: { path: { name } },
    body: { new_name: newName },
  });
  if (data) return data;
  throw new CalibratorApiError(detailMessage(error, `could not rename ${name}`));
}

export async function getColourReport(name: string): Promise<ColourReportRow[]> {
  const { data, error } = await api.GET("/api/templates/{name}/colour-report", {
    params: { path: { name } },
  });
  if (error || !data) throw new CalibratorApiError(`could not read the colour report for ${name}`);
  return data;
}

export async function assignKind(name: string, kind: TemplateKind): Promise<TemplateConfigState> {
  const { data, error } = await api.POST("/api/templates/{name}/kind", {
    params: { path: { name } },
    body: { kind },
  });
  if (error) throw new CalibratorApiError(`could not set the kind for ${name}`);
  return withTuples<TemplateConfigState>(data);
}

export async function listDesigns(): Promise<DesignSummary[]> {
  const { data, error } = await api.GET("/api/designs");
  if (error || !data) throw new CalibratorApiError("failed to list test designs");
  return data;
}

export async function uploadDesign(file: File): Promise<DesignSummary> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.POST("/api/designs", { body: formBody(form) });
  if (!data) throw new CalibratorApiError("failed to upload test design");
  return data;
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

export function templatePhotoUrl(name: string, colour?: string | null): string {
  const base = `/api/templates/${encodeURIComponent(name)}/photo`;
  return colour ? `${base}?colour=${encodeURIComponent(colour)}` : base;
}

export function designThumbnailUrl(id: string): string {
  return `/api/designs/${encodeURIComponent(id)}/thumbnail`;
}

export function templateDesignPreviewUrl(
  name: string,
  design: string | { testDesign: string },
  colour?: string | null,
): string {
  // A listing's design by name, or -- the listing-template editor's preview
  // (UI doc §3) -- a calibrator test design by its library id.
  const params = new URLSearchParams(
    typeof design === "string" ? { design } : { test_design: design.testDesign },
  );
  if (colour) params.set("colour", colour);
  return `/api/templates/${encodeURIComponent(name)}/design-preview?${params.toString()}`;
}

export async function getTemplateSwatch(name: string, colour: string): Promise<string> {
  const { data, error } = await api.GET("/api/templates/{name}/swatch", {
    params: { path: { name }, query: { colour } },
  });
  if (error || !data) throw new CalibratorApiError(`no swatch for ${name} colour ${colour}`);
  return data.hex;
}

export type PositionedListing = components["schemas"]["PositionedListingResponse"];

export async function getPositionedListings(name: string): Promise<PositionedListing[]> {
  const { data, error } = await api.GET("/api/templates/{name}/positioned-listings", {
    params: { path: { name } },
  });
  if (error || !data) throw new CalibratorApiError(`could not read listings positioned on ${name}`);
  return data;
}

type PreviewBody = {
  calibration_revision?: string;
  /** The labels `calibration_revision` was saved with. */
  labels?: string[];
  mask_edits?: MaskEdit[];
} & (
  | { colour: string; bounding_box: BoundingBox; renderer: Renderer }
  | { placements: Placement[]; renderer: Renderer }
  | { bounding_box: BoundingBox; renderer: Renderer }
);

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
