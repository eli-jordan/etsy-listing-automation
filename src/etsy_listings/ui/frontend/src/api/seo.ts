import { api } from "./client";
import type { SeoReadinessResponse } from "../types";

/**
 * AI Mode's readiness check (AI SEO implementation plan, PR7). Generation
 * itself is an AI run: `api/aiRuns.ts`.
 */

export class SeoApiError extends Error {}

/** Whether the **AI Mode** button can start a run for this saved listing
 * right now -- the server applies `POST /api/ai/runs`'s own rules. The
 * control stays visible and disabled when the response is not ready. */
export async function getSeoReadiness(name: string): Promise<SeoReadinessResponse> {
  const { data, error } = await api.GET("/api/listings/{name}/ai-seo/readiness", {
    params: { path: { name } },
  });
  if (error || !data) throw new SeoApiError(`could not check AI Mode readiness for ${name}`);
  return data;
}
