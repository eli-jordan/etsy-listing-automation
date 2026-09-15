import { api } from "./client";
import type {
  CommonMediaSummary,
  CreateListingRequest,
  GarmentProfileSummary,
  ListingDesignSummary,
  ListingDetail,
  ListingSummary,
  PricingPlanSummary,
  WorkspaceSummary,
} from "../types";

/**
 * The listings UI's whole HTTP surface (phase 5). Mirrors `api/calibrator.ts`'s
 * shape exactly: typed wrapper functions over `openapi-fetch`, the only thing
 * pages/components import.
 */

export class ListingsApiError extends Error {}

export async function listListings(): Promise<ListingSummary[]> {
  const { data, error } = await api.GET("/api/listings");
  if (error || !data) throw new ListingsApiError("could not load listings");
  return data;
}

export async function getListing(name: string): Promise<ListingDetail> {
  const { data, error } = await api.GET("/api/listings/{name}", {
    params: { path: { name } },
  });
  if (error || !data) throw new ListingsApiError(`could not load listing ${name}`);
  return data;
}

/** A partial `listing.yaml` document -- merged server-side, one level deep on
 * `etsy:` (see `ui/api/listings.py`'s `_merge`). Always resolves: an invalid
 * candidate comes back as a 200 with `field_errors` populated and nothing
 * written, so the caller never has to branch on the HTTP status to render
 * inline validation. */
export async function patchListing(
  name: string,
  patch: Record<string, unknown>,
): Promise<ListingDetail> {
  const { data, error } = await api.PATCH("/api/listings/{name}", {
    params: { path: { name } },
    body: patch,
  });
  if (error || !data) throw new ListingsApiError(`could not save listing ${name}`);
  return data;
}

export async function createListing(body: CreateListingRequest): Promise<ListingDetail> {
  const { data, error } = await api.POST("/api/listings", { body });
  if (error || !data) throw new ListingsApiError("could not create listing");
  return data;
}

export async function listGarmentProfiles(): Promise<GarmentProfileSummary[]> {
  const { data, error } = await api.GET("/api/garment-profiles");
  if (error || !data) throw new ListingsApiError("could not load garment profiles");
  return data;
}

export async function listPricingPlans(garmentProfile: string): Promise<PricingPlanSummary[]> {
  const { data, error } = await api.GET("/api/pricing-plans", {
    params: { query: { garment_profile: garmentProfile } },
  });
  if (error || !data) throw new ListingsApiError("could not load pricing plans");
  return data;
}

export async function listCommonMedia(): Promise<CommonMediaSummary[]> {
  const { data, error } = await api.GET("/api/common-media");
  if (error || !data) throw new ListingsApiError("could not load shared images");
  return data;
}

/** The shared asset's own picture. A URL, like the two thumbnails above. */
export function commonMediaThumbnailUrl(name: string): string {
  return `/api/common-media/${encodeURIComponent(name)}/thumbnail`;
}

export async function getWorkspace(): Promise<WorkspaceSummary> {
  const { data, error } = await api.GET("/api/workspace");
  if (error || !data) throw new ListingsApiError("could not load the workspace");
  return data;
}

/** A URL, not a fetch -- the browser loads it as an `<img src>`, the same
 * shape `templateThumbnailUrl` already uses for the calibrator's rail. */
export function listingDesignThumbnailUrl(name: string): string {
  return `/api/listing-designs/${encodeURIComponent(name)}/thumbnail`;
}

export async function listListingDesigns(): Promise<ListingDesignSummary[]> {
  const { data, error } = await api.GET("/api/listing-designs");
  if (error || !data) throw new ListingsApiError("could not load listing designs");
  return data;
}
