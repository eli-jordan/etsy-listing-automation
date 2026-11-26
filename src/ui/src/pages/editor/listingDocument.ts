import type { ListingDetail } from "../../types";

/** The fields of a `ListingDetail` that are `listing.yaml`. `Listing` forbids
 * extra fields, so sending the whole detail back is a 200 with `field_errors`
 * and nothing written. Listed positively, so a new computed field is never
 * written by accident. */
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
    template_positions: detail.template_positions,
  };
}
