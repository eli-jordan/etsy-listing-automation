import { api, detailMessage, formBody, withTuples } from "./client";
import type {
  CommonCopySummary,
  MediaFileSummary,
  CreateListingRequest,
  EtsySectionSummary,
  EtsySectionsResponse,
  GarmentProfileSummary,
  ListingDesignSummary,
  ListingDetail,
  ListingSummary,
  PricingPlanSummary,
  WorkspaceSummary,
} from "../types";

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
  return withTuples<ListingDetail>(data);
}

/** The same, but `null` on a 404 rather than a thrown error -- what the
 * deploy view uses to tell "this listing no longer exists" (a retract just
 * applied, decision 11) apart from a genuine failure it should surface. */
export async function tryGetListing(name: string): Promise<ListingDetail | null> {
  const { data, error, response } = await api.GET("/api/listings/{name}", {
    params: { path: { name } },
  });
  if (response.status === 404) return null;
  if (error || !data) throw new ListingsApiError(`could not load listing ${name}`);
  return withTuples<ListingDetail>(data);
}

export async function patchListing(
  name: string,
  patch: Record<string, unknown>,
): Promise<ListingDetail> {
  const { data, error } = await api.PATCH("/api/listings/{name}", {
    params: { path: { name } },
    body: patch,
  });
  if (error || !data) throw new ListingsApiError(`could not save listing ${name}`);
  return withTuples<ListingDetail>(data);
}

export async function getListingDraft(): Promise<ListingDetail> {
  const { data, error } = await api.GET("/api/listing-draft");
  if (error || !data) throw new ListingsApiError("could not start a new listing");
  return withTuples<ListingDetail>(data);
}

export async function describeListingDraft(
  document: Record<string, unknown>,
): Promise<ListingDetail> {
  const { data, error } = await api.POST("/api/listing-draft", { body: { document } });
  if (error || !data) throw new ListingsApiError("could not check the draft");
  return withTuples<ListingDetail>(data);
}

/** Naming a listing is what creates it. Resolves for a document the server
 * would not write, exactly as `patchListing` does -- `field_errors` is set and
 * `name` comes back empty, which is the "not created" signal. It *rejects*
 * only for what a name can be wrong about: not a usable directory name (400),
 * or already taken (409). */
export async function createListing(body: CreateListingRequest): Promise<ListingDetail> {
  const { data, error } = await api.POST("/api/listings", { body });
  if (error || !data) throw new ListingsApiError("could not create listing");
  return withTuples<ListingDetail>(data);
}

export async function deleteListing(name: string): Promise<ListingSummary | null> {
  const { data, error, response } = await api.DELETE("/api/listings/{name}", {
    params: { path: { name } },
  });
  if (response?.status === 204) return null;
  if (error || !data) throw new ListingsApiError(`could not delete listing ${name}`);
  return data as ListingSummary;
}

export async function renameListing(name: string, newName: string): Promise<ListingDetail> {
  const { data, error } = await api.POST("/api/listings/{name}/rename", {
    params: { path: { name } },
    body: { new_name: newName },
  });
  if (error || !data) throw new ListingsApiError(`could not rename ${name} to ${newName}`);
  return withTuples<ListingDetail>(data);
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

export async function listCommonMedia(): Promise<MediaFileSummary[]> {
  const { data, error } = await api.GET("/api/common-media");
  if (error || !data) throw new ListingsApiError("could not load shared files");
  return data;
}

export async function listListingMediaFiles(listing: string): Promise<MediaFileSummary[]> {
  const { data, error } = await api.GET("/api/listings/{listing}/media-files", {
    params: { path: { listing } },
  });
  if (error || !data) throw new ListingsApiError("could not load this listing's files");
  return data;
}

/** A file's path under its directory, escaped a segment at a time so the
 * slashes of a subdirectory stay slashes. */
function mediaPath(name: string): string {
  return name.split("/").map(encodeURIComponent).join("/");
}

/** One of the listing's own files, downscaled for a list. Images only: a
 * video answers `415`, since a `<video>` element draws its own poster. */
export function listingMediaThumbnailUrl(listing: string, name: string): string {
  return `/api/listings/${encodeURIComponent(listing)}/media-files/${mediaPath(name)}/thumbnail`;
}

export function listingMediaFileUrl(listing: string, name: string): string {
  return `/api/listings/${encodeURIComponent(listing)}/media-files/${mediaPath(name)}/file`;
}

export function listingScenePreviewUrl(
  listing: string,
  template: string,
  colour: string | null,
  cacheKey: string,
): string {
  const params = new URLSearchParams({ template });
  if (colour) params.set("colour", colour);
  params.set("v", cacheKey);
  return `/api/listings/${encodeURIComponent(listing)}/scene-preview?${params.toString()}`;
}

/** Whether the scene a `listingScenePreviewUrl` showed was drawn from stale
 * remembered pixel digests. Any other URL, and any failure, is "unchanged". */
export async function scenePreviewChanged(url: string): Promise<boolean> {
  const match = /^\/api\/listings\/([^/?]+)\/scene-preview\?(.*)$/.exec(url);
  const [, name, query] = match ?? [];
  if (name === undefined || query === undefined) return false;
  const params = new URLSearchParams(query);
  const template = params.get("template");
  if (template === null) return false;
  const colour = params.get("colour");
  const { data, error } = await api.GET("/api/listings/{name}/scene-preview/check", {
    params: {
      path: { name: decodeURIComponent(name) },
      query: colour === null ? { template } : { template, colour },
    },
  });
  return !error && data?.changed === true;
}

export function listingSceneArtworkUrl(
  listing: string,
  template: string,
  colour: string | null,
  placement: string | null,
  cacheKey: string,
): string {
  const params = new URLSearchParams({ template, v: cacheKey });
  if (colour) params.set("colour", colour);
  if (placement) params.set("placement", placement);
  return `/api/listings/${encodeURIComponent(listing)}/scene-artwork?${params.toString()}`;
}

export function commonMediaThumbnailUrl(name: string): string {
  return `/api/common-media/${mediaPath(name)}/thumbnail`;
}

export function commonMediaFileUrl(name: string): string {
  return `/api/common-media/${mediaPath(name)}/file`;
}

/** The Description tab's common-copy selector (AI SEO implementation plan,
 * PR6): every reusable description body, each with a ref ready to write
 * straight into `description.ref`. Empty (never an error) for a workspace
 * with no `common-copy/` yet, the same convention `listEtsySections` follows
 * for an unconfigured shop -- an editor with nothing to pick from is an
 * ordinary state, not a failure. */
export async function listCommonCopy(): Promise<CommonCopySummary[]> {
  try {
    const { data, error } = await api.GET("/api/common-copy");
    if (error || !data) return [];
    return data;
  } catch {
    return [];
  }
}

export async function getWorkspace(): Promise<WorkspaceSummary> {
  const { data, error } = await api.GET("/api/workspace");
  if (error || !data) throw new ListingsApiError("could not load the workspace");
  return data;
}

export function listingDesignThumbnailUrl(name: string): string {
  return `/api/listing-designs/${encodeURIComponent(name)}/thumbnail`;
}

export async function listListingDesigns(): Promise<ListingDesignSummary[]> {
  const { data, error } = await api.GET("/api/listing-designs");
  if (error || !data) throw new ListingsApiError("could not load listing designs");
  return data;
}

/** Adds a PNG to `designs/` and answers where it landed -- not always its
 * filename: a name taken by other artwork gets a `-2` suffix. Hand-rolled
 * multipart, as `uploadDesign` is; the error carries the server's reason. */
export async function uploadListingDesign(file: File): Promise<ListingDesignSummary> {
  const form = new FormData();
  form.append("file", file);
  const { data, error } = await api.POST("/api/listing-designs", { body: formBody(form) });
  if (!data) throw new ListingsApiError(detailMessage(error, `could not upload ${file.name}`));
  return data;
}

export async function listEtsySections(): Promise<EtsySectionsResponse> {
  try {
    const { data, error } = await api.GET("/api/etsy/sections");
    if (error || !data) return { available: false, sections: [] };
    return data;
  } catch {
    return { available: false, sections: [] };
  }
}

export async function createEtsySection(title: string): Promise<EtsySectionSummary> {
  const { data, error } = await api.POST("/api/etsy/sections", {
    body: { title },
  });
  if (error || !data) throw new ListingsApiError("could not create Etsy section");
  return data;
}
