import { api } from "./client";
import type { DesignBriefResponse, SeoProposalResponse, SeoReadinessResponse } from "../types";

/**
 * Listing SEO AI Mode's HTTP surface (AI SEO implementation plan, PR7).
 * Mirrors `api/listings.ts`'s shape: typed wrapper functions over
 * `openapi-fetch`, the only thing components import.
 *
 * Deliberately its own module rather than more of `listings.ts`: every other
 * function there resolves to a plain value or throws `ListingsApiError`, but
 * a proposal request has a third outcome ordinary listing calls never do --
 * the browser itself aborted it (the settled "Cancellation" decision) -- and
 * that needs to reach the caller as data, not as a distinguishable exception
 * a caller would have to sniff `DOMException.name` out of.
 */

export class SeoApiError extends Error {}

/** Whether **AI Mode** can be enabled for this saved listing right now.
 * The control stays visible and disabled when the response is not ready. */
export async function getSeoReadiness(name: string): Promise<SeoReadinessResponse> {
  const { data, error } = await api.GET("/api/listings/{name}/ai-seo/readiness", {
    params: { path: { name } },
  });
  if (error || !data) throw new SeoApiError(`could not check AI Mode readiness for ${name}`);
  return data;
}

export type SeoProposalOutcome =
  { kind: "success"; proposal: SeoProposalResponse } | { kind: "cancelled" } | { kind: "failed" };

/** Run one complete AI Mode SEO request for this saved listing
 * (`POST /api/listings/{name}/ai-seo/proposal`).
 *
 * `signal` is the caller's `AbortController` -- aborted when the seller
 * presses **Cancel** or leaves the Details tab (the settled "Cancellation"
 * decision: "The browser aborts a request when its editor is left or its
 * connection closes"). This never rejects: an abort resolves `"cancelled"`
 * and every other failure -- a 409/502/503 the backend answers with, or the
 * fetch itself throwing for any other reason -- resolves `"failed"`, because
 * the interaction contract (`docs/ui-listing-seo-interactions.md` section 2)
 * only distinguishes cancelled from failed from success; the backend's exact
 * status code is not a distinction the UI makes. */
export async function requestSeoProposal(
  name: string,
  signal: AbortSignal,
): Promise<SeoProposalOutcome> {
  try {
    const { data, error } = await api.POST("/api/listings/{name}/ai-seo/proposal", {
      params: { path: { name } },
      signal,
    });
    if (error || !data) return { kind: "failed" };
    return { kind: "success", proposal: data };
  } catch (err) {
    if (signal.aborted || (err instanceof DOMException && err.name === "AbortError")) {
      return { kind: "cancelled" };
    }
    return { kind: "failed" };
  }
}

export type DesignBriefOutcome =
  { kind: "success"; brief: string } | { kind: "cancelled" } | { kind: "failed" };

/** Draft a listing brief from a design image (`POST /api/ai/design-brief`,
 * PRD 68).
 *
 * Takes the design and the garment profile rather than a listing name,
 * because the moment a brief is wanted is the moment a design is attached --
 * which, while a seller is creating a listing, is before it has a name or a
 * file. `design` is workspace-relative (`designs/take-a-hike.png`): see
 * `media.ts.workspacePath`.
 *
 * The same three outcomes a proposal request has, for the same reason -- and
 * with more riding on the third here, because nobody asked for this request.
 * A workspace with no `prompts/brief.md`, or a signed-out CLI, answers 409;
 * the seller should simply find the Brief field empty and AI Mode disabled
 * with its usual explanation, not an error about something they never did.
 */
export async function requestDesignBrief(
  design: string,
  garmentProfile: string,
  signal: AbortSignal,
): Promise<DesignBriefOutcome> {
  try {
    const { data, error } = await api.POST("/api/ai/design-brief", {
      body: { design, garment_profile: garmentProfile },
      signal,
    });
    if (error || !data) return { kind: "failed" };
    return { kind: "success", brief: (data as DesignBriefResponse).brief };
  } catch (err) {
    if (signal.aborted || (err instanceof DOMException && err.name === "AbortError")) {
      return { kind: "cancelled" };
    }
    return { kind: "failed" };
  }
}
