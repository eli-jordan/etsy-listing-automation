import { api } from "./client";
import type {
  CommonMediaSummary,
  CreateListingRequest,
  EtsySectionSummary,
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

/** The empty document `+ New listing` opens the editor on: nothing chosen, an
 * empty `name`, and a block issue for each thing still to pick. Built
 * server-side so the starting shape of a listing is not also invented here.
 * See `ui/api/listings.py`'s `listing_draft`. */
export async function getListingDraft(): Promise<ListingDetail> {
  const { data, error } = await api.GET("/api/listing-draft");
  if (error || !data) throw new ListingsApiError("could not start a new listing");
  return data;
}

/** The same, for a candidate the editor has since edited -- recomputed issues
 * and field errors, still written nowhere. This is what keeps the issues banner
 * true while the listing has no name, which is the only channel an unsaved
 * listing has for being told what it is missing. */
export async function describeListingDraft(
  document: Record<string, unknown>,
): Promise<ListingDetail> {
  const { data, error } = await api.POST("/api/listing-draft", { body: { document } });
  if (error || !data) throw new ListingsApiError("could not check the draft");
  return data;
}

/** Naming a listing is what creates it. Resolves for a document the server
 * would not write, exactly as `patchListing` does -- `field_errors` is set and
 * `name` comes back empty, which is the "not created" signal. It *rejects*
 * only for what a name can be wrong about: not a usable directory name (400),
 * or already taken (409). */
export async function createListing(body: CreateListingRequest): Promise<ListingDetail> {
  const { data, error } = await api.POST("/api/listings", { body });
  if (error || !data) throw new ListingsApiError("could not create listing");
  return data;
}

/** Move a listing to a new name, directory and render cache together.
 *
 * Rejects where `patchListing` resolves, and the asymmetry is the point: a
 * *document* the server will not write is answered with `field_errors` on a
 * 200, because the editor shows those inline and keeps going. A *name* it will
 * not take is a 400 or a 409, because there is nothing to show inline and the
 * only useful answer is to say so beside the name field. */
export async function renameListing(name: string, newName: string): Promise<ListingDetail> {
  const { data, error } = await api.POST("/api/listings/{name}/rename", {
    params: { path: { name } },
    body: { new_name: newName },
  });
  if (error || !data) throw new ListingsApiError(`could not rename ${name} to ${newName}`);
  return data;
}

export async function listGarmentProfiles(): Promise<GarmentProfileSummary[]> {
  const { data, error } = await api.GET("/api/garment-profiles");
  if (error || !data) throw new ListingsApiError("could not load garment profiles");
  return data;
}

/** Every plan, each flagged for whether it was built for *this* garment.
 * `garmentProfile` is empty for a listing that has not chosen one yet: there is
 * then nothing to be compatible with, and the editor drops the "different
 * garment" note rather than claiming every plan differs from a garment nobody
 * picked. */
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

/** The shared asset's own picture, downscaled for a list. A URL, like the two
 * thumbnails above. */
export function commonMediaThumbnailUrl(name: string): string {
  return `/api/common-media/${encodeURIComponent(name)}/thumbnail`;
}

/** The same asset at its own size -- what the preview pane shows and what the
 * lightbox opens. The thumbnail is 160px on its longest edge, which is a
 * picture to *pick* rather than one to judge. */
export function commonMediaFileUrl(name: string): string {
  return `/api/common-media/${encodeURIComponent(name)}/file`;
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

/** The live shop's sections, for the Details tab's Section dropdown. Empty
 * (never an error, never a rejected promise) for a workspace with no
 * `shop_id` or Etsy app key pair yet -- the caller falls back to a plain
 * text field in that case, with nothing to catch. */
export async function listEtsySections(): Promise<EtsySectionSummary[]> {
  try {
    const { data, error } = await api.GET("/api/etsy/sections");
    if (error || !data) return [];
    return data;
  } catch {
    return [];
  }
}
