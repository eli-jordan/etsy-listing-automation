// Fixture values for the Admin page directions. Shaped like what a settings
// API would hand the page: saved values, plus the live lists each picker offers.

export type ProviderId = "codex" | "claude" | "grok";

export interface ProviderRow {
  id: ProviderId;
  name: string;
  enabled: boolean;
  model: string;
  effort: string;
  /** What the CLI reports about itself right now. */
  status: "ready" | "signed-out" | "missing";
  statusText: string;
  models: { id: string; label: string }[];
  efforts: string[];
  /** Set when the saved model or effort is no longer offered (Q21). */
  stale?: string;
  /** Where the model list came from, shown beside the picker. */
  source: string;
}

export const providers: ProviderRow[] = [
  {
    id: "claude",
    name: "Claude",
    enabled: true,
    model: "claude-opus-5-5",
    effort: "high",
    status: "ready",
    statusText: "Signed in",
    models: [
      { id: "", label: "Account default" },
      { id: "claude-opus-5-5", label: "claude-opus-5-5" },
      { id: "claude-sonnet-5-5", label: "claude-sonnet-5-5" },
      { id: "claude-haiku-5-5", label: "claude-haiku-5-5" },
    ],
    efforts: ["Default", "low", "medium", "high", "xhigh", "max"],
    source: "Curated list",
  },
  {
    id: "codex",
    name: "Codex",
    enabled: true,
    model: "gpt-6.1-sol",
    effort: "medium",
    status: "ready",
    statusText: "Signed in",
    models: [
      { id: "", label: "Account default" },
      { id: "gpt-6.1-sol", label: "GPT-6.1-Sol" },
      { id: "gpt-6-astra", label: "GPT-6-Astra" },
      { id: "gpt-6.1-terra", label: "GPT-6.1 Terra" },
      { id: "gpt-6-sol", label: "GPT-6-Sol" },
    ],
    efforts: ["Default", "low", "medium", "high", "xhigh", "max"],
    source: "From codex debug models",
  },
  {
    id: "grok",
    name: "Grok",
    enabled: false,
    model: "grok-4.4",
    effort: "Default",
    status: "ready",
    statusText: "Signed in with grok.com",
    models: [
      { id: "", label: "Account default (grok-4.7)" },
      { id: "grok-4.7", label: "grok-4.7" },
      { id: "grok-4.7-build-fast", label: "grok-4.7-build-fast" },
      { id: "grok-4.6", label: "grok-4.6" },
      { id: "grok-4.5", label: "grok-4.5" },
    ],
    efforts: ["Default", "low", "medium", "high"],
    stale: "grok-4.4 is no longer offered by the Grok CLI. Runs still pass it; if Grok refuses it, the chain moves on.",
    source: "From grok models",
  },
];

export const batchConcurrency = 2;

export interface Weight {
  key: string;
  label: string;
  hint: string;
  value: number;
  fallback: number;
}

export const weights: Weight[] = [
  { key: "reviews", label: "Reviews", hint: "Total reviews on the listing", value: 30, fallback: 30 },
  { key: "favourites_per_day", label: "Favourites per day", hint: "Favourites since listed, per day", value: 35, fallback: 30 },
  { key: "search_rank", label: "Search rank", hint: "Position in Etsy's results", value: 20, fallback: 20 },
  { key: "views_per_day", label: "Views per day", hint: "Views since listed, per day", value: 10, fallback: 10 },
  { key: "shop_sales", label: "Shop sales", hint: "The seller's total sales", value: 5, fallback: 5 },
  { key: "shop_rating", label: "Shop rating", hint: "The seller's average rating", value: 0, fallback: 5 },
];

export const weightTotal = weights.reduce((sum, w) => sum + w.value, 0);
export const share = (value: number) => Math.round((value / weightTotal) * 100);

export const shop = {
  etsy: {
    shopName: "NaturallyInkedStudio",
    shopId: "48210377",
    currency: "USD",
  },
  printify: {
    shopName: "NaturallyInked on Etsy",
    shopId: "19884321",
  },
  listing: {
    whoMade: "someone_else",
    whenMade: "made_to_order",
    isSupply: false,
    renewal: "manual",
    shippingProfile: "Printify US standard",
    returnPolicy: "No returns, exchanges within 30 days",
    productionPartner: "Printify",
    printProvider: "Monster Digital",
  },
};

export const whoMadeOptions = [
  { id: "i_did", label: "I did" },
  { id: "collective", label: "A member of my shop" },
  { id: "someone_else", label: "Another company or person" },
];

export const whenMadeOptions = [
  { id: "made_to_order", label: "Made to order" },
  { id: "2020_2026", label: "2020 – 2026" },
  { id: "2010_2019", label: "2010 – 2019" },
];

export const shippingProfiles = ["Printify US standard", "Printify EU standard", "Free shipping (US)"];
export const returnPolicies = ["No returns, exchanges within 30 days", "Returns and exchanges within 14 days"];
export const productionPartners = ["Printify"];
export const printProviders = ["Monster Digital", "SwiftPOD", "Print Geek", "Fulfill Engine"];
