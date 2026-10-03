import type { WorkflowStep } from "../../screens/marketSeo/AiWorkflowIndicator";
import type { MarketListing, MarketPhrase, MarketResearch } from "../../screens/marketSeo/MarketListingsPanel";

export const queries = ["retro sunset hiking shirt", "take a hike t shirt", "vintage mountain graphic tee"];

export const brief =
  "Retro graphic of a winding mountain trail under a warm sunset, with the exact words “Take A Hike” in a rounded 70s typeface above it.";

const listing = (
  rank: number,
  title: string,
  shop: string,
  score: number,
  metrics: Pick<MarketListing, "reviews" | "favouritesPerDay" | "viewsPerDay" | "shopRating">,
  thumb: MarketListing["thumb"],
  tags: string[],
  lead: string,
  extra: Partial<MarketListing> = {},
): MarketListing => ({ id: 1400000000 + rank * 7919, rank, title, shop, score, ...metrics, thumb, tags, lead, ...extra });

export const listings: MarketListing[] = [
  listing(1, "Take A Hike Shirt, Retro Hiking Tee, Mountain Sunset Graphic T-Shirt, Hiker Gift", "TrailheadPrintCo", 94,
    { reviews: 1284, favouritesPerDay: 18.4, viewsPerDay: 212, shopRating: 4.9 },
    { shirt: "#e9dcc4", ink: "#c2562b", motif: "sun" },
    ["take a hike shirt", "retro hiking shirt", "hiker gift", "mountain graphic tee", "sunset t shirt", "hiking tee", "camping shirt", "outdoor lover gift", "comfort colors tee", "nature shirt", "adventure tee", "gift for hikers", "national park tee"],
    "Take a hike — literally — in this retro mountain sunset tee, printed on a soft Comfort Colors shirt."),
  listing(2, "Vintage Mountain Shirt, Retro Sunset Hiking T Shirt, Comfort Colors Outdoor Tee", "WildGroveGoods", 89,
    { reviews: 942, favouritesPerDay: 15.1, viewsPerDay: 188, shopRating: 4.8 },
    { shirt: "#3f5a4a", ink: "#f2b25c", motif: "peaks" },
    ["vintage mountain shirt", "retro hiking shirt", "sunset hiking tee", "comfort colors tee", "outdoor shirt", "mountain lover gift", "hiker gift", "camping tee", "nature lover shirt", "trail shirt", "granola girl shirt", "adventure shirt", "70s graphic tee"],
    "A faded 70s-style mountain sunset for trail days, road trips and everything between."),
  listing(3, "Take A Hike Retro T-Shirt, Funny Hiking Shirt, Camping Gift for Him or Her", "SummitAndSage", 83,
    { reviews: 610, favouritesPerDay: 12.9, viewsPerDay: 140, shopRating: 4.9 },
    { shirt: "#d9c7a8", ink: "#6b4a8a", motif: "sun" },
    ["take a hike shirt", "funny hiking shirt", "camping gift", "hiker gift", "retro hiking shirt", "outdoor lover gift", "gift for hikers", "hiking humor", "mountain tee", "travel shirt", "nature tee", "unisex tee", "hiking t shirt"],
    "Tell them to take a hike (nicely) with this retro trail tee — a gift for hikers with a sense of humour."),
  listing(4, "Mountain Sunset Graphic Tee, Retro Outdoor Shirt, Hiking Lover T-Shirt", "Pine & Thread", 78,
    { reviews: 214, favouritesPerDay: 9.6, viewsPerDay: 121, shopRating: 4.9 },
    { shirt: "#f1e6d2", ink: "#2f5e6e", motif: "peaks" },
    ["mountain graphic tee", "retro outdoor shirt", "hiking lover gift", "sunset t shirt", "hiker gift", "camping shirt", "nature shirt", "adventure tee", "trail shirt", "outdoorsy gift", "unisex tee", "comfort colors tee", "national park tee"],
    "A warm mountain sunset in retro stripes, for anyone happiest at the trailhead.",
    { ownShop: true }),
  listing(5, "Retro National Park Shirt, Hiking Tee, Mountain Sunset Vintage T-Shirt", "OldTrailOutfitters", 74,
    { reviews: 1920, favouritesPerDay: 6.2, viewsPerDay: 96, shopRating: 4.7 },
    { shirt: "#8a5a3b", ink: "#f4d6a0", motif: "peaks" },
    ["national park shirt", "retro hiking shirt", "vintage mountain tee", "hiker gift", "camping shirt", "road trip tee", "outdoor lover gift", "nature shirt", "adventure shirt", "sunset t shirt", "trail tee", "gift for hikers", "unisex shirt"],
    "Our best-selling national park design, washed in sunset colours on a garment-dyed tee."),
  listing(6, "Take A Hike Sweatshirt Style Tee, Retro Mountain Shirt, Hiking Club Gift", "HappyCampersCo", 69,
    { reviews: 388, favouritesPerDay: 8.1, viewsPerDay: 77, shopRating: 4.8 },
    { shirt: "#c9d3c0", ink: "#914b2c", motif: "sun" },
    ["take a hike shirt", "hiking club shirt", "retro mountain shirt", "hiker gift", "camping tee", "outdoor shirt", "gift for hikers", "mountain tee", "nature shirt", "trail shirt", "retro tee", "adventure shirt", "girls trip shirt"],
    "Start a hiking club of your own with this retro take-a-hike tee."),
  listing(7, "Hiking Shirt, Retro Sunset Mountain Tee, Nature Lover Gift, Trail Shirt", "NorthboundThreads", 64,
    { reviews: 176, favouritesPerDay: 7.4, viewsPerDay: 88, shopRating: 5.0 },
    { shirt: "#efe3cf", ink: "#b8433a", motif: "peaks" },
    ["hiking shirt", "retro sunset tee", "nature lover gift", "trail shirt", "mountain tee", "hiker gift", "outdoor shirt", "camping shirt", "retro hiking shirt", "adventure tee", "sunset t shirt", "gift for hikers", "wanderlust shirt"],
    "Soft, faded and made for the trail — a retro sunset over the peaks."),
  listing(8, "Retro Hiking T Shirt, Vintage Outdoor Adventure Tee, Mountain Graphic Shirt", "MeadowAndMoss", 60,
    { reviews: 95, favouritesPerDay: 6.9, viewsPerDay: 70, shopRating: 4.9 },
    { shirt: "#2e3a4f", ink: "#f0a35e", motif: "sun" },
    ["retro hiking shirt", "vintage outdoor tee", "adventure shirt", "mountain graphic tee", "hiker gift", "camping tee", "nature shirt", "outdoor lover gift", "trail tee", "sunset shirt", "wanderlust tee", "unisex shirt", "gift for hikers"],
    "A vintage-inspired adventure tee for hikers, campers and weekend wanderers."),
  listing(9, "Mountain Tee, Hiking Gift, Retro Graphic Shirt", "ThePeakPress", 55,
    { reviews: 64, favouritesPerDay: 5.1, viewsPerDay: 61, shopRating: 4.6 },
    { shirt: "#e4d4b8", ink: "#3b6b4f", motif: "peaks" }, [], ""),
  listing(10, "Take A Hike Funny Shirt, Hiking T-Shirt", "GoodTrailCo", 51,
    { reviews: 41, favouritesPerDay: 4.8, viewsPerDay: 55, shopRating: 4.8 },
    { shirt: "#f6efe2", ink: "#a0522d", motif: "sun" }, [], ""),
  listing(11, "Sunset Mountains Retro Tee, Camping Shirt", "CampfireCollective", 47,
    { reviews: 120, favouritesPerDay: 2.9, viewsPerDay: 49, shopRating: 4.7 },
    { shirt: "#5b4a6e", ink: "#f7c77a", motif: "peaks" }, [], ""),
  listing(12, "Retro Outdoors Shirt, Hiker Tee, Adventure Gift", "BackcountryBasics", 44,
    { reviews: 28, favouritesPerDay: 3.6, viewsPerDay: 38, shopRating: 4.9 },
    { shirt: "#d3c2a4", ink: "#7a3b2e", motif: "sun" }, [], ""),
];

export const phrases: MarketPhrase[] = [
  { phrase: "retro hiking shirt", listings: 12, score: 1, used: true },
  { phrase: "hiker gift", listings: 14, score: 0.94, used: true },
  { phrase: "take a hike shirt", listings: 7, score: 0.81, used: true },
  { phrase: "gift for hikers", listings: 9, score: 0.72, used: false },
  { phrase: "mountain graphic tee", listings: 6, score: 0.66, used: true },
  { phrase: "outdoor lover gift", listings: 8, score: 0.63, used: true },
  { phrase: "sunset t shirt", listings: 6, score: 0.57, used: false },
  { phrase: "camping shirt", listings: 7, score: 0.52, used: false },
  { phrase: "comfort colors tee", listings: 4, score: 0.48, used: false },
  { phrase: "national park tee", listings: 4, score: 0.41, used: true },
  { phrase: "nature shirt", listings: 8, score: 0.39, used: true },
  { phrase: "adventure shirt", listings: 6, score: 0.35, used: true },
];

export const research: MarketResearch = {
  queries,
  found: 58,
  scored: 20,
  searchedAgo: "just now",
  listings,
  phrases,
};

export const steps = {
  briefActive: [
    { id: "brief", state: "active", detail: "Reading take-a-hike.png" },
    { id: "market", state: "pending" },
    { id: "seo", state: "pending" },
  ],
  researching: [
    { id: "brief", state: "done", detail: "Drafted from take-a-hike.png" },
    { id: "market", state: "active", detail: "Searching Etsy for 3 phrases…" },
    { id: "seo", state: "pending" },
  ],
  suggesting: [
    { id: "brief", state: "done", detail: "Drafted from take-a-hike.png" },
    { id: "market", state: "done", detail: "20 listings scored, from 58 found" },
    { id: "seo", state: "active", detail: "Writing for 0:14" },
  ],
  ready: [
    { id: "brief", state: "done", detail: "Drafted from take-a-hike.png" },
    { id: "market", state: "done", detail: "20 listings scored, from 58 found" },
    { id: "seo", state: "done", detail: "3 titles, 20 tags, 3 leads to review" },
  ],
  briefSkipped: [
    { id: "brief", state: "skipped", detail: "You wrote the brief, so it was kept" },
    { id: "market", state: "active", detail: "Searching Etsy for 3 phrases…" },
    { id: "seo", state: "pending" },
  ],
  noComparables: [
    { id: "brief", state: "done", detail: "Drafted from take-a-hike.png" },
    { id: "market", state: "warning", detail: "No comparable listings found, even with filters relaxed" },
    { id: "seo", state: "active", detail: "Writing from the design and brief alone" },
  ],
  marketFailed: [
    { id: "brief", state: "done", detail: "Drafted from take-a-hike.png" },
    { id: "market", state: "failed", detail: "Etsy market search failed: Etsy did not respond (HTTP 503) after 3 retries" },
    { id: "seo", state: "pending", detail: "Not started" },
  ],
} satisfies Record<string, WorkflowStep[]>;
