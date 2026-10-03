import type { ListingDetail } from "../../types";

/** The fields of a `ListingDetail` that are actually `listing.yaml`.
 *
 * `ListingDetail` is a `Listing` plus what the editor needs and a listing
 * never stores -- `status`, `issues`, the remote ids, the resolved prices.
 * PATCH bodies are merged into the stored document, and `Listing` forbids
 * extra fields, so sending the whole object back is a 200 with
 * `field_errors` and nothing written.
 *
 * Listed positively rather than as a set of keys to delete: a new *computed*
 * field on `ListingDetail` should not silently start being written to
 * `listing.yaml`, whereas a new real listing field failing to round-trip is
 * visible the moment it is edited.
 */
export function listingDocument(detail: ListingDetail): Record<string, unknown> {
  return {
    garment_profile: detail.garment_profile,
    design: detail.design,
    colors: detail.colors,
    brief: detail.brief,
    prices: detail.prices,
    pricing_plan: detail.pricing_plan,
    price_overrides: detail.price_overrides,
    etsy: detail.etsy,
    media: detail.media,
  };
}
