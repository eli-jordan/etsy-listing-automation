import { api } from "./client";
import type { ListingProposal, ProposalResolutionPatch, SeoReadinessResponse } from "../types";

export class SeoApiError extends Error {}

export async function getSeoReadiness(name: string): Promise<SeoReadinessResponse> {
  const { data, error } = await api.GET("/api/listings/{name}/ai-seo/readiness", {
    params: { path: { name } },
  });
  if (error || !data) throw new SeoApiError(`could not check AI Mode readiness for ${name}`);
  return data;
}

export async function getListingProposal(name: string): Promise<ListingProposal | null> {
  const { data, error, response } = await api.GET("/api/listings/{name}/proposal", {
    params: { path: { name } },
  });
  if (response.status === 404) return null;
  if (error || !data) throw new SeoApiError(`could not read the AI proposal for ${name}`);
  return data;
}

export async function resolveListingProposal(
  name: string,
  patch: ProposalResolutionPatch,
): Promise<ListingProposal | null> {
  const { data, error, response } = await api.PATCH("/api/listings/{name}/proposal/resolution", {
    params: { path: { name } },
    body: patch,
  });
  if (response.status === 404 || response.status === 412) return null;
  if (error || !data) throw new SeoApiError(`could not record the AI proposal choice for ${name}`);
  return data;
}
