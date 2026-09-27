// ListingDetail fixtures for the listing-template editor and a batch-created
// listing, plus a hand-set AI Mode state for the real DetailsTab.
import type { AiSeoMode } from "../../../src/pages/editor/aiSeo/useAiSeoMode";
import type { ListingDetail, SeoProposalResponse } from "../../../src/types";

const prices = ["S", "M", "L", "XL", "2XL", "3XL"].map((size) => ({
  size,
  amount: size === "2XL" ? "379 NOK" : size === "3XL" ? "399 NOK" : "349 NOK",
}));

const body =
  "Garment-dyed 100% ring-spun cotton, relaxed fit. Printed to order in Europe. Wash inside out at 30°C.";

/** A listing template, shaped as the editor's `ListingDetail`: no design,
 * brief or SEO copy, so every tab previews with the calibrator test design. */
export function templateDetail(over: Partial<ListingDetail> = {}): ListingDetail {
  return {
    name: "heavyweight-tee",
    garment_profile: "comfort-colors-1717",
    garment_brand: "Comfort Colors",
    garment_model: "1717",
    garment_product_type: "tee",
    garment_materials: ["ring-spun cotton"],
    colors: ["black", "ivory", "moss", "blue-jean", "pepper"],
    design: {},
    artwork: {},
    brief: "",
    prices: {},
    price_overrides: {},
    pricing_plan: "pricing/standard-nok.yaml",
    pricing_plan_name: "Standard NOK",
    resolved_prices: prices,
    etsy: {
      title: "",
      tags: [],
      description: { lead: "", text: body, ref: null },
      section: "Hiking tees",
      renewal: "auto",
      shipping_profile: "Norway Post",
      variation_images: "flat-lay",
    },
    media: [
      { template: "lifestyle-porch", colour: null },
      { template: "flat-lay", colour: "black" },
      { template: "flat-lay", colour: "ivory" },
      "./size-chart.png",
    ],
    description_composed: body,
    status: "draft",
    issues: [],
    field_errors: {},
    etsy_listing_id: null,
    printify_product_id: null,
    modified_at: "2026-09-27T11:38:00Z",
    lifecycle: null,
    ...over,
  };
}

/** The same template mid-edit with every colour switched off: incomplete,
 * so the last complete version stays saved. */
export const incompleteTemplate = templateDetail({
  colors: [],
  issues: [
    {
      severity: "block",
      tab: "variants",
      where: "Colours",
      message: "Turn on at least one colour.",
    },
  ],
});

const brief =
  "Hand-drawn forest trail after rain, puddles on the path and mist in the pines. Words: “after rain”. Soft, calm mood, not sporty.";

const tags = [
  "rainy day hike",
  "forest trail tee",
  "hiking shirt",
  "pnw graphic tee",
  "misty mountains",
  "hiker gift",
  "nature lover tee",
  "trail runner",
  "outdoor shirt",
  "comfort colors tee",
  "camping tee",
  "rain lover gift",
  "adventure tee",
];

/** A listing created by the batch: brief written by AI and edited since,
 * tags accepted, title and lead still waiting on an out-of-date proposal. */
export const batchListing: ListingDetail = templateDetail({
  name: "after-rain-trail-2",
  design: { default: "designs/after-rain-trail-2.png" },
  brief,
  etsy: {
    ...templateDetail().etsy,
    tags,
    description: { lead: "", text: body, ref: null },
  },
  description_composed: body,
  modified_at: "2026-09-27T12:10:00Z",
  issues: [
    { severity: "block", tab: "details", where: "Title", message: "Add a title before deploying." },
    {
      severity: "block",
      tab: "details",
      where: "Description lead",
      message: "Add a description lead before deploying.",
    },
  ],
});

const proposal: SeoProposalResponse = {
  titles: [
    "After Rain Trail Tee, Misty Forest Hiking Shirt",
    "Rainy Day Hiker Graphic Tee, Pacific Northwest Trail",
    "After The Rain Mountain Path Shirt for Hikers",
  ],
  tags: [...tags, "misty forest", "rainy hike", "trail tee", "pnw hiker", "forest shirt", "rain gift", "mountain path"],
  description_leads: [
    "A calm, hand-drawn trail after the rain — mist in the pines and puddles on the path, for hikers who love quiet mornings.",
    "Bring the hush of a forest after rain to an everyday tee, with a hand-drawn trail and the words “after rain.”",
    "For rainy-day walkers and trail lovers: a soft, misty forest path drawn by hand on a relaxed garment-dyed tee.",
  ],
  rationale: [],
  warnings: [],
  observed_text: "after rain",
  snapshot: {
    brief: "Hand-drawn forest trail after rain, puddles on the path and mist in the pines. Words: “after rain”.",
    product_type: "tee",
    etsy_category: "",
    materials: ["ring-spun cotton"],
    colors: ["black", "ivory", "moss", "blue-jean", "pepper"],
    garment_brand: "Comfort Colors",
    garment_model: "1717",
    garment_profile: "comfort-colors-1717",
    design: { default: "designs/after-rain-trail-2.png" },
    design_content_hash: null,
  },
  generated_at: "2026-09-27T11:55:00Z",
  expires_at: "2099-01-01T00:00:00Z",
};

const noop = () => {};

/** AI Mode as the editor holds it after a batch run: one proposal, tags
 * accepted, title and lead unresolved, and out of date because the brief was
 * edited after it was written. */
export const staleAiSeo: AiSeoMode = {
  available: true,
  requirements: [],
  reason: null,
  phase: "idle",
  proposal: { proposal, unresolved: { title: true, tags: false, lead: true } },
  stale: true,
  generate: noop,
  draftsBrief: false,
  cancel: noop,
  failure: null,
  startedAt: null,
  run: {
    phase: "idle",
    busy: false,
    steps: [],
    queries: null,
    market: null,
    proposal: null,
    message: null,
    startedAt: null,
    start: noop,
    cancel: noop,
    arm: noop,
    autoNotice: false,
    dismissAutoNotice: noop,
  },
  market: null,
  chooseTitle: noop,
  rejectTitle: noop,
  chooseLead: noop,
  rejectLead: noop,
  toggleTag: noop,
  acceptBestTags: noop,
  closeTags: noop,
};
