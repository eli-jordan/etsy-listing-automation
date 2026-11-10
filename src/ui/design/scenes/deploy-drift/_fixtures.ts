import type { PlanDTO } from "../../../src/types";

export const listingName = "nan-dont-count-on-it";
export const etsyListingId = 4604946928;

export type DriftKind = "formatting" | "wording" | "setting";

export interface DriftedField {
  id: "title" | "description" | "shipping";
  label: string;
  kind: DriftKind;
  /** What the last apply wrote. */
  lastApplied: string;
  /** What Etsy reports now. */
  live: string;
  /** What this plan would write. */
  after: string;
  /** One plain sentence: what really differs. */
  verdict: string;
  /** The differences alone, for a one-line summary. */
  summary: { from: string; to: string; count?: number };
}

const appliedDescription = `This JavaScript shirt is a NaN Don't Count On It funny web developer tee made for developers who know NaN's unruly reputation, a unisex garment-dyed Comfort Colors® 1717 T-shirt with a crisp pixel-art coding humor graphic for workdays, meetups, and off-hours.

✨OUR HAPPINESS GUARANTEE✨

If you’re not completely happy with your order, simply reach out within 14 days of receiving your shirt.
We’ll gladly offer a full refund or send a replacement - whichever works best for you!

✨FINDING YOUR PERFECT FIT✨

Our Comfort Colors tees have a relaxed, boxy fit for casual comfort.

✔ Check the size chart in the product photos to find your best fit.
✔ For an oversized look, consider ordering one to two sizes up.

✨PRODUCTION & SHIPPING TIMES✨

Processing Time: 1-5 business days
Standard Shipping: 2-5 business days after production

✨WHAT MAKES OUR SHIRTS SPECIAL?✨

We use Comfort Colors 1717 tees, known for their quality and comfort. Each shirt features:

✔ 100% ring-spun cotton for a soft feel
✔ Garment-dyed & preshrunk to minimize shrinkage and offer a vintage look.
✔ Made in the USA for top-notch craftsmanship
✔ DTG (Direct-to-Garment) printing — no vinyl, just high-quality ink
✔ Eco-friendly, non-toxic inks for a sustainable choice

✨HOW TO CARE FOR YOUR SHIRT✨

To keep your tee looking its best:

✔ Wash inside out on a gentle cycle with cold water
✔ Air dry or tumble dry on low heat

✨COLOR NOTICE✨

Colors may appear slightly different due to screen settings, resolution, and lighting.
While we aim for accuracy, slight variations may occur.`;

const appliedTitle =
  "JavaScript Shirt, NaN Don't Count On It Funny Web Developer Tee, TypeScript Frontend Gift, Programmer Humor, Comfort Colors® 1717 T-Shirt";
const editedTitle =
  "JavaScript Shirt, NaN Don't Count On It Funny Coder Tee, Programmer Humor, Comfort Colors® 1717 T-Shirt";

export const title: DriftedField = {
  id: "title",
  label: "Title",
  kind: "wording",
  lastApplied: appliedTitle,
  live: editedTitle,
  after: appliedTitle,
  verdict: "The wording was edited on Etsy.",
  summary: { from: "Web Developer Tee, TypeScript Frontend Gift,", to: "Coder Tee," },
};

export const description: DriftedField = {
  id: "description",
  label: "Description",
  kind: "formatting",
  lastApplied: appliedDescription,
  live: appliedDescription.replaceAll("'", "&#39;"),
  after: appliedDescription,
  verdict: "Same words. Etsy reports 2 apostrophes as &#39; instead.",
  summary: { from: "'", to: "&#39;", count: 2 },
};

export const shipping: DriftedField = {
  id: "shipping",
  label: "Shipping profile",
  kind: "setting",
  lastApplied: "Norway standard",
  live: "Printify default",
  after: "Norway standard",
  verdict: "Printify re-attached its own profile when it republished.",
  summary: { from: "Norway standard", to: "Printify default" },
};

export const driftedFields = [title, description, shipping];

export const kindLabels: Record<DriftKind, string> = {
  formatting: "Formatting only",
  wording: "Wording edited",
  setting: "Setting changed",
};

export const colours = ["berry", "black", "butter", "chambray", "espresso", "grey", "ivory", "moss", "orchid", "white", "yam"];
export const tags = ["javascript", "developer t shirt", "programmer tshirt", "developer gift", "computer science", "javascript shirt", "nan shirt", "computer nerd shirt", "comfort colors 1717", "typescript shirt", "developer shirt", "debugging shirt", "coding shirt"];
export const materials = ["Ring Spun Cotton"];
export const priceRange = "282–336 NOK";

const garment: Record<string, string> = {
  black: "#2c2a28",
  white: "#f3efe7",
  yam: "#b8622f",
  moss: "#3f4a35",
  orchid: "#b9a3c4",
  berry: "#7c2a44",
  ivory: "#e9dcc0",
};

/** A synthetic mockup: no shop photography belongs in the repo. */
function tee(colour: string): string {
  const fill = garment[colour] ?? "#888";
  const ink = colour === "white" || colour === "ivory" || colour === "orchid" ? "#201e1d" : "#f5ead8";
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"><rect width="200" height="200" fill="#d9ccb6"/><path d="M68 34 40 46 18 84l26 14 10-14v92h92V84l10 14 26-14-22-38-28-12c-5 12-16 18-32 18s-27-6-32-18Z" fill="${fill}"/><text x="100" y="112" text-anchor="middle" font-family="monospace" font-weight="700" font-size="26" fill="${ink}">NaN</text></svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

export const beforeTiles = ["black", "white", "yam", "moss", "orchid", "berry", "ivory"].map(tee);
export const afterTiles = [
  { src: tee("ivory"), movedFrom: 7 },
  { src: tee("white"), movedFrom: null },
  { src: tee("black"), movedFrom: 1 },
  { src: tee("yam"), movedFrom: 3 },
  { src: tee("moss"), movedFrom: 4 },
  { src: tee("orchid"), movedFrom: 5 },
  { src: tee("berry"), movedFrom: 6 },
];

const work = (reason: string, actions: string[]) => ({
  type: "work",
  reason,
  changes: [],
  actions: actions.map((text) => ({ description: text, outputs: [] })),
});
const none = { type: "no_work", reason: "No changes", changes: [], actions: [] };

export const plan = {
  etsy_listing_id: etsyListingId,
  stage_plans: [
    { stage: "render", drift: [], outcome: work("design or template changed", ["Render mockups"]) },
    { stage: "printify_product", drift: [], outcome: none },
    { stage: "publish", drift: [], outcome: none },
    { stage: "etsy_listing", drift: [], outcome: work("Etsy disagrees with what was last applied -- re-asserting", ["Patch the listing"]) },
    { stage: "etsy_media", drift: [], outcome: work("the media manifest changed", ["Reorder images"]) },
    { stage: "etsy_videos", group: "etsy_media", drift: [], outcome: none },
  ],
} as unknown as PlanDTO;
