import type { MaskEdit } from "./preparation";
import { api } from "./client";
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

/**
 * Returns null when the template has no template.yaml yet -- a folder of
 * photos that has not been given a kind.
 *
 * The cast is because openapi-fetch widens `bounding_box`'s 4-tuple to a
 * plain array when inferring the response type of a 3-way discriminated
 * union -- the server still enforces exactly 4 points either way.
 */
const templateRevisions = new Map<string, string>();
export interface TemplateConfigDocument {
  config: TemplateConfigState;
  modifiedAt: string;
}

export async function getTemplateConfig(name: string): Promise<TemplateConfigDocument | null> {
  const { data, error, response } = await api.GET("/api/templates/{name}/config", {
    params: { path: { name } },
  });
  if (error) return null;
  const modifiedAt = response.headers.get("Last-Modified");
  if (modifiedAt === null) throw new CalibratorApiError("template config has no modification time");
  const revision = response.headers.get("ETag");
  if (revision) templateRevisions.set(name, revision);
  return { config: data as unknown as TemplateConfigState, modifiedAt };
}

/** Revision acknowledged by this client's last config read or successful save. */
export function acknowledgedTemplateRevision(name: string): string {
  return (templateRevisions.get(name) ?? "").replace(/^"|"$/g, "");
}

function canonicalConfig(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalConfig);
  if (value !== null && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonicalConfig(item)]),
    );
  return value;
}

/** Accept this editor's completed baseline revision only while the saved
 * configuration and the coordinator's exact revision still match the disk. */
export async function refreshPreparedRevision(
  name: string,
  savedConfig: TemplateConfigState,
  preparedRevision: string,
): Promise<boolean> {
  const expected = '"' + preparedRevision + '"';
  if (templateRevisions.get(name) === expected) return true;
  const { data, error, response } = await api.GET("/api/templates/{name}/config", {
    params: { path: { name } },
  });
  if (
    error ||
    response.headers.get("ETag") !== expected ||
    JSON.stringify(canonicalConfig(data)) !== JSON.stringify(canonicalConfig(savedConfig))
  )
    return false;
  templateRevisions.set(name, expected);
  return true;
}

async function writeTemplateConfig(
  name: string,
  config: TemplateConfigState,
  maskEdits: MaskEdit[] = [],
): Promise<TemplateConfigState> {
  const { data, error, response } = await api.PUT("/api/templates/{name}/config", {
    params: { path: { name }, header: { "if-match": templateRevisions.get(name) ?? "" } },

    body: { request_id: crypto.randomUUID(), config, mask_edits: maskEdits },
  });
  if (error)
    throw new CalibratorApiError(
      response?.status === 409 || response?.status === 412
        ? "Template changed elsewhere. Reload before saving."
        : "could not save template.yaml",
    );
  const revision = response?.headers.get("ETag");
  if (revision) templateRevisions.set(name, revision);
  return data as unknown as TemplateConfigState;
}

// Keep one revision-bearing save in flight per template. Operations are objects
// shared by successive draft snapshots; consume each only after its commit.
const pendingSaves = new Map<string, Promise<TemplateConfigState>>();
const committedOperations = new WeakSet<MaskEdit["operations"][number]>();
export function saveTemplateConfig(
  name: string,
  config: TemplateConfigState,
  maskEdits: MaskEdit[] = [],
): Promise<TemplateConfigState> {
  const previous = pendingSaves.get(name);
  const write = async () => {
    const edits = maskEdits
      .map((edit) => ({
        ...edit,
        operations: edit.operations.filter((op) => !committedOperations.has(op)),
      }))
      .filter((edit) => edit.operations.length > 0);
    const saved = await writeTemplateConfig(name, config, edits);
    for (const edit of edits)
      for (const operation of edit.operations) committedOperations.add(operation);
    return saved;
  };
  const promise = previous ? previous.then(write) : write();
  pendingSaves.set(name, promise);
  void promise
    .finally(() => {
      if (pendingSaves.get(name) === promise) pendingSaves.delete(name);
    })
    .catch(() => {});
  return promise;
}
/** What each photo will be taken as if this becomes a colour-matrix set.
 * Reporting only -- ADR-0004 makes the filename the source of truth. */
export async function getColourReport(name: string): Promise<ColourReportRow[]> {
  const { data, error } = await api.GET("/api/templates/{name}/colour-report", {
    params: { path: { name } },
  });
  if (error || !data) throw new CalibratorApiError(`could not read the colour report for ${name}`);
  return data;
}

/** The first calibration step. Writes the starting template.yaml for that
 * shape; refused if one already exists, since kind decides the whole file
 * shape (ADR-0014) and changing it would discard the old shape's calibration. */
export async function assignKind(name: string, kind: TemplateKind): Promise<TemplateConfigState> {
  const { data, error } = await api.POST("/api/templates/{name}/kind", {
    params: { path: { name } },
    body: { kind },
  });
  if (error) throw new CalibratorApiError(`could not set the kind for ${name}`);
  return data as unknown as TemplateConfigState;
}

/** The calibrator's test-design library: three bundled targets plus whatever
 * the user has uploaded into the workspace. */
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

/** A test design, small -- the listing-template editor's preview row. */
export function designThumbnailUrl(id: string): string {
  return `/api/designs/${encodeURIComponent(id)}/thumbnail`;
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
  | { colour: string; bounding_box: BoundingBox; renderer: Renderer }
  | { placements: Placement[]; renderer: Renderer }
  | { bounding_box: BoundingBox; renderer: Renderer };

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
