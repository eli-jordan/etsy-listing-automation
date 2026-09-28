import { api } from "./client";
import type { ListingProposal, ProposalResolutionPatch, SeoReadinessResponse } from "../types";

/**
 * AI Mode's readiness check (AI SEO implementation plan, PR7) and the
 * listing's cached proposal (A41). Generation itself is an AI run:
 * `api/aiRuns.ts`.
 */

export class SeoApiError extends Error {}

/** Whether the **AI Mode** button can start a run for this saved listing
 * right now. An empty brief is allowed: the click drafts one. The control
 * stays visible and disabled when the response is not ready. */
export async function getSeoReadiness(name: string): Promise<SeoReadinessResponse> {
  const { data, error } = await api.GET("/api/listings/{name}/ai-seo/readiness", {
    params: { path: { name } },
  });
  if (error || !data) throw new SeoApiError(`could not check AI Mode readiness for ${name}`);
  return data;
}

/** The listing's cached proposal, judged stale by the server against the
 * saved listing, or `null` when it has none (A41). */
export async function getListingProposal(name: string): Promise<ListingProposal | null> {
  const { data, error, response } = await api.GET("/api/listings/{name}/proposal", {
    params: { path: { name } },
  });
  if (response.status === 404) return null;
  if (error || !data) throw new SeoApiError(`could not read the AI proposal for ${name}`);
  return data;
}

/** Records accepted or dismissed sections of the proposal generated at
 * `patch.generated_at`. `null` when that proposal is gone (404) or was
 * replaced by a newer one (409): the caller reads the current one again. */
export async function resolveListingProposal(
  name: string,
  patch: ProposalResolutionPatch,
): Promise<ListingProposal | null> {
  const { data, error, response } = await api.PATCH("/api/listings/{name}/proposal/resolution", {
    params: { path: { name } },
    body: patch,
  });
  if (response.status === 404 || response.status === 409) return null;
  if (error || !data) throw new SeoApiError(`could not record the AI proposal choice for ${name}`);
  return data;
}
