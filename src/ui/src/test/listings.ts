import type { ListingDetail } from "../types";

type EtsyBlock = ListingDetail["etsy"];

/** An empty Etsy block: no title, lead, tags, section or profiles. Scenarios
 * name the fields they depend on. */
export function listingEtsy(over: Partial<EtsyBlock> = {}): EtsyBlock {
  return {
    title: "",
    description: { lead: "", text: null, ref: null },
    tags: [],
    variation_images: null,
    renewal: null,
    section: null,
    shipping_profile: null,
    ...over,
  };
}

/** A saved, never-deployed `take-a-hike` draft on one black Comfort Colors
 * 1717 with a default design and nothing else filled in.
 *
 * Each test file wraps this with the facts its scenarios share (a pricing
 * plan, a brief, deployed ids), so the overrides stay visible beside the
 * cases that rely on them. */
export function listingDetail(over: Partial<ListingDetail> = {}): ListingDetail {
  return {
    garment_profile: "comfort-colors-1717",
    design: { default: "designs/take-a-hike.png" },
    colors: ["black"],
    brief: "",
    prices: {},
    price_overrides: {},
    artwork: {},
    pricing_plan: null,
    etsy: listingEtsy(),
    media: [],
    name: "take-a-hike",
    modified_at: "2026-09-17T10:00:00Z",
    status: "draft",
    issues: [],
    field_errors: {},
    etsy_listing_id: null,
    printify_product_id: null,
    pricing_plan_name: null,
    resolved_prices: [],
    gestures: [],
    description_composed: "",
    ...over,
  };
}
