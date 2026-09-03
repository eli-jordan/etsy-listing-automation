import { api } from "./client";
import type { Quad, RenderConfigState, TemplateSummary } from "../types";

/**
 * The calibrator's whole HTTP surface. Everything above this file works in
 * domain types and never touches fetch, URLs or the generated schema.
 *
 * It also re-narrows the quad. The generated client models what survives JSON
 * serialisation, so the four-corner tuple arrives typed as `number[][]` --
 * checking the shape here, once, is what lets the rest of the app rely on
 * "exactly four corners" instead of re-checking or casting at every use.
 */

export class CalibratorApiError extends Error {}

function toQuad(points: number[][]): Quad {
  if (points.length !== 4 || points.some((p) => p.length !== 2)) {
    throw new CalibratorApiError(
      `expected a quad of 4 [x, y] corners, got ${JSON.stringify(points)}`,
    );
  }
  return points.map(([x, y]) => [x, y] as [number, number]) as Quad;
}

export async function listTemplates(): Promise<TemplateSummary[]> {
  const { data, error } = await api.GET("/api/templates");
  if (error) throw new CalibratorApiError("could not load templates");
  return data;
}

/** Returns null when the template has no template.yaml yet (a fresh upload). */
export async function getTemplateConfig(name: string): Promise<RenderConfigState | null> {
  const { data, error } = await api.GET("/api/templates/{name}/config", {
    params: { path: { name } },
  });
  if (error) return null;
  return { ...data, warp: { quad: toQuad(data.warp.quad) } };
}

export async function saveTemplateConfig(name: string, config: RenderConfigState): Promise<void> {
  const { error } = await api.PUT("/api/templates/{name}/config", {
    params: { path: { name } },
    body: config,
  });
  if (error) throw new CalibratorApiError("could not save template.yaml");
}

/**
 * Renders a preview through the real server-side pipeline. Returns an object
 * URL the caller owns and must revoke.
 */
export async function renderPreview(
  name: string,
  colour: string,
  config: RenderConfigState,
): Promise<string> {
  const response = await fetch(`/api/templates/${encodeURIComponent(name)}/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ colour, ...config }),
  });
  if (!response.ok) {
    throw new CalibratorApiError(`preview failed for ${colour}`);
  }
  return URL.createObjectURL(await response.blob());
}
