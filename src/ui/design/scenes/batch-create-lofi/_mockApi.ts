// Fixture-backed stand-in for the app's HTTP API, so frames can mount the
// real editor components (VariantsTab, PricingTab, ImagesTab, DetailsTab,
// DesignSelect) exactly as they ship. Nothing leaves the frame: every /api
// request is answered from the fixtures below, and every /api image URL is
// pointed at a local asset.
//
// Must be imported BEFORE anything from src/: the app's API client captures
// `fetch` when its module first evaluates.
import mockupBlack from "../../assets/batch-deploy/mockup-black.png";
import mockupIvory from "../../assets/batch-deploy/mockup-ivory.png";
import mockupLifestyle from "../../assets/batch-deploy/mockup-lifestyle.png";
import mockupMoss from "../../assets/batch-deploy/mockup-moss.png";
import afterRain from "../../assets/batch-create/after-rain-trail.svg";
import cedarTrail from "../../assets/batch-create/cedar-trail.svg";
import fjordMornings from "../../assets/batch-create/fjord-mornings.svg";
import nightHike from "../../assets/batch-create/night-hike-club.svg";
import sizeChart from "../../assets/batch-create/size-chart.svg";
import type {
  CommonCopySummary,
  EtsySectionSummary,
  GarmentProfileSummary,
  ListingDesignSummary,
  MediaFileSummary,
  PricingPlanSummary,
  TemplateSummary,
} from "../../../src/types";

const PROFILE = "comfort-colors-1717";

export const garmentProfiles: GarmentProfileSummary[] = [
  {
    name: PROFILE,
    sizes: ["S", "M", "L", "XL", "2XL", "3XL"],
    colors: {
      black: "dark",
      ivory: "light",
      moss: "dark",
      "blue-jean": "dark",
      pepper: "dark",
      butter: "light",
    },
    materials: ["ring-spun cotton"],
    preview_template: "flat-lay",
  },
];

const swatches: Record<string, string> = {
  black: "#1f1d1c",
  ivory: "#efe7d4",
  moss: "#5f6b3c",
  "blue-jean": "#6c7f94",
  pepper: "#4a4744",
  butter: "#f0d98c",
};

const matrixColours = Object.keys(swatches);

export const templates: TemplateSummary[] = [
  {
    name: "flat-lay",
    kind: "colour-matrix",
    colours: matrixColours,
    has_config: true,
    status: "calibrated",
    photos: matrixColours.map((c) => ({ colour: c, file: `flat-lay-${c}.jpg` })),
  },
  {
    name: "lifestyle-porch",
    kind: "single",
    colours: [],
    has_config: true,
    status: "calibrated",
    photos: [{ colour: null, file: "lifestyle-porch.jpg" }],
  },
  {
    name: "close-up",
    kind: "colour-matrix",
    colours: ["black", "moss"],
    has_config: true,
    status: "calibrated",
    photos: [
      { colour: "black", file: "close-up-black.jpg" },
      { colour: "moss", file: "close-up-moss.jpg" },
    ],
  },
];

const pricingPlans: PricingPlanSummary[] = [
  { ref: "pricing/standard-nok.yaml", name: "Standard NOK", garment_profile: PROFILE, compatible: true },
  { ref: "pricing/premium-nok.yaml", name: "Premium NOK", garment_profile: PROFILE, compatible: true },
];

const commonMedia: MediaFileSummary[] = [
  { ref: "media/care-guide.png", name: "care-guide.png", file: "media/care-guide.png", kind: "image" },
  { ref: "media/shop-banner.png", name: "shop-banner.png", file: "media/shop-banner.png", kind: "image" },
];

const localMedia: MediaFileSummary[] = [
  { ref: "./size-chart.png", name: "size-chart.png", file: "size-chart.png", kind: "image" },
];

const commonCopy: CommonCopySummary[] = [
  {
    ref: "common-copy/comfort-colors-standard.md",
    title: "Comfort Colors · standard fit and care",
    summary: "Garment-dyed ring-spun cotton, relaxed fit, care notes.",
  },
  { ref: "common-copy/gift-note.md", title: "Gift note", summary: "Packed as a gift on request." },
];

const sections: EtsySectionSummary[] = [
  { id: 1, title: "Hiking tees" },
  { id: 2, title: "Outdoor gifts" },
];

export const listingDesigns: ListingDesignSummary[] = [
  { name: "after-rain-trail-2", file: "designs/after-rain-trail-2.png" },
  { name: "night-hike-club", file: "designs/night-hike-club.png" },
  { name: "cedar-trail", file: "designs/cedar-trail.png" },
  { name: "fjord-mornings", file: "designs/fjord-mornings.png" },
];

/** The design artwork each fixture name draws with. */
export const designArt: Record<string, string> = {
  "after-rain-trail-2": afterRain,
  "after-rain-trail": afterRain,
  "night-hike-club": nightHike,
  "cedar-trail": cedarTrail,
  "fjord-mornings": fjordMornings,
  "fjord-mornings-final": fjordMornings,
};

function jsonFor(path: string, query: URLSearchParams): unknown {
  if (path === "/api/garment-profiles") return garmentProfiles;
  if (path === "/api/templates") return templates;
  if (/^\/api\/templates\/[^/]+\/swatch$/.test(path)) {
    return { hex: swatches[query.get("colour") ?? ""] ?? "#888888" };
  }
  if (path === "/api/pricing-plans") return pricingPlans;
  if (path === "/api/common-media") return commonMedia;
  if (/^\/api\/listings\/[^/]+\/media-files$/.test(path)) return localMedia;
  if (path === "/api/common-copy") return commonCopy;
  if (path === "/api/etsy/sections") return sections;
  if (path === "/api/listing-designs") return listingDesigns;
  if (path === "/api/workspace") return { shop_name: "North & Pine Studio", storage_id: "fixture" };
  return undefined;
}

const realFetch = globalThis.fetch.bind(globalThis);

globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  const url = new URL(raw, location.href);
  if (!url.pathname.startsWith("/api/")) return realFetch(input, init);
  const body = jsonFor(url.pathname, url.searchParams);
  if (body === undefined) {
    return new Response(JSON.stringify({ detail: "Not in the design fixtures" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  }
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
};

/** Which local picture stands in for an /api image URL. */
export function fixturePicture(raw: string): string {
  if (!raw.startsWith("/api/")) return raw;
  const url = new URL(raw, location.href);
  const path = decodeURIComponent(url.pathname);
  const colour = url.searchParams.get("colour");
  const design = url.searchParams.get("design");
  const template = /^\/api\/templates\/([^/]+)\//.exec(path)?.[1];
  if (template === "lifestyle-porch") return mockupLifestyle;
  if (template !== undefined) {
    if (design !== null && colour === null) return mockupLifestyle;
    if (colour === "ivory" || colour === "butter") return mockupIvory;
    if (colour === "moss") return mockupMoss;
    return mockupBlack;
  }
  const designName = /^\/api\/listing-designs\/([^/]+)\//.exec(path)?.[1];
  if (designName !== undefined) return designArt[designName] ?? afterRain;
  if (path.includes("size-chart")) return sizeChart;
  if (path.includes("care-guide")) return mockupLifestyle;
  if (path.includes("shop-banner")) return mockupIvory;
  return mockupIvory;
}

// React writes `src` both ways, depending on the element; catch both.
const srcDescriptor = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, "src");
if (srcDescriptor?.set) {
  Object.defineProperty(HTMLImageElement.prototype, "src", {
    ...srcDescriptor,
    set(value: string) {
      srcDescriptor.set?.call(this, fixturePicture(String(value)));
    },
  });
}
const realSetAttribute = Element.prototype.setAttribute;
Element.prototype.setAttribute = function (name: string, value: string) {
  if (name === "src" && (this instanceof HTMLImageElement || this instanceof HTMLVideoElement)) {
    return realSetAttribute.call(this, name, fixturePicture(String(value)));
  }
  return realSetAttribute.call(this, name, value);
};
