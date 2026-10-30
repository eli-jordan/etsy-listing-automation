// Fixtures for the Shop tab. Shaped like what a shop-settings API would hand the
// page: the signed-in Etsy shop, the Printify shops the token can reach (each
// marked linked or not), the listing defaults, and the copy for every info card.

export const etsy = {
  account: "NaturallyInked",
  userId: "81120455",
  shopName: "NaturallyInkedStudio",
  shopId: "48210377",
  currency: "USD",
  signedInSince: "12 Aug 2026",
};

export const printifyToken = { tail: "a91f", addedOn: "3 Jul 2026" };

export interface PrintifyShop {
  id: string;
  title: string;
  channel: "etsy" | "api";
  /** Linked = connected to Etsy and named after the signed-in Etsy shop. */
  linked: boolean;
  current?: boolean;
  why?: string;
}

export const printifyShops: PrintifyShop[] = [
  { id: "19884321", title: "NaturallyInkedStudio", channel: "etsy", linked: true, current: true },
  {
    id: "19902455",
    title: "NaturallyInked Test",
    channel: "api",
    linked: false,
    why: "An API store: not connected to Etsy, so nothing created there can be published.",
  },
  {
    id: "18810036",
    title: "TakeAHikeTees",
    channel: "etsy",
    linked: false,
    why: "Publishes to a different Etsy shop, TakeAHikeTees.",
  },
];

export const counts = { deployed: 14, drafts: 6 };

/** The shop a switch would move to, as Etsy reports it after signing in. */
export const nextEtsy = {
  account: "TakeAHike",
  shopName: "TakeAHikeTees",
  shopId: "51007712",
  currency: "NOK",
  printifyShop: "TakeAHikeTees",
  printifyShopId: "18810036",
};

// Etsy Payments' supported list, checked 2026-10-30:
// https://help.etsy.com/hc/en-us/articles/360000337767-Currencies-Supported-for-Etsy-Payments
export const currencies = [
  { id: "USD", label: "USD · US dollar" },
  { id: "AUD", label: "AUD · Australian dollar" },
  { id: "CAD", label: "CAD · Canadian dollar" },
  { id: "CNY", label: "CNY · Chinese yuan" },
  { id: "DKK", label: "DKK · Danish krone" },
  { id: "EUR", label: "EUR · Euro" },
  { id: "GBP", label: "GBP · British pound" },
  { id: "HKD", label: "HKD · Hong Kong dollar" },
  { id: "IDR", label: "IDR · Indonesian rupiah" },
  { id: "ILS", label: "ILS · Israeli shekel" },
  { id: "MAD", label: "MAD · Moroccan dirham" },
  { id: "MXN", label: "MXN · Mexican peso" },
  { id: "MYR", label: "MYR · Malaysian ringgit" },
  { id: "NOK", label: "NOK · Norwegian krone" },
  { id: "NZD", label: "NZD · New Zealand dollar" },
  { id: "PHP", label: "PHP · Philippine peso" },
  { id: "SEK", label: "SEK · Swedish krona" },
  { id: "SGD", label: "SGD · Singapore dollar" },
  { id: "CHF", label: "CHF · Swiss franc" },
  { id: "TRY", label: "TRY · Turkish lira" },
  { id: "VND", label: "VND · Vietnamese dong" },
  { id: "ZAR", label: "ZAR · South African rand" },
];

export type Tier = "pod" | "custom";

export const tiers: { id: Tier; label: string; blurb: string; recommended?: boolean }[] = [
  {
    id: "pod",
    label: "Print on demand",
    blurb: "Printify prints and ships each order. Fills in what Etsy requires for this.",
    recommended: true,
  },
  { id: "custom", label: "Custom", blurb: "Choose each field yourself." },
];

/** What the Print on demand tier fixes, as Etsy names it. */
export const podFields = [
  { key: "whoMade", label: "Who made it", value: "Another company or person" },
  { key: "whenMade", label: "When it was made", value: "Made to order" },
  { key: "isSupply", label: "What it is", value: "A finished product" },
];

export const defaults = {
  whoMade: "someone_else",
  whenMade: "made_to_order",
  isSupply: false,
  productionPartner: "Printify",
  renewal: "manual",
  shippingProfile: "Printify US standard",
  returnPolicy: "No returns, exchanges within 30 days",
  printProvider: "Monster Digital",
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
export const supplyOptions = [
  { id: "product", label: "A finished product" },
  { id: "supply", label: "A craft supply or tool" },
];
export const renewalOptions = [
  { id: "manual", label: "Manual" },
  { id: "auto", label: "Automatic" },
];
export const shippingProfiles = ["Printify US standard", "Printify EU standard", "Free shipping (US)"];
export const returnPolicies = ["No returns, exchanges within 30 days", "Returns and exchanges within 14 days"];
export const productionPartners = ["Printify"];
export const printProviders = ["Monster Digital", "SwiftPOD", "Print Geek", "Fulfill Engine"];

export interface Info {
  title: string;
  what: string;
  effect: string;
  /** Where the value lives: shop.yaml key, or "Read from Etsy". */
  source: string;
}

export const info: Record<string, Info> = {
  etsyShop: {
    title: "Etsy shop",
    what: "The shop every listing deploys to. It is the shop owned by the Etsy account you signed in with; an Etsy account owns one shop.",
    effect: "Read-only here. It changes only if you sign in to Etsy with a different account.",
    source: "etsy.shop_id",
  },
  printifyShop: {
    title: "Printify shop",
    what: "Where products are created and published from: the Printify shop connected to your Etsy shop.",
    effect: "Read-only here. It follows the Etsy shop, so the two can't point at different places.",
    source: "printify.shop_id",
  },
  link: {
    title: "Why the shops are linked",
    what: "Printify publishes to exactly one Etsy shop. A Printify shop is linked when it is connected to Etsy and named after your Etsy shop.",
    effect: "Picking the Etsy shop picks the Printify shop. You can't pair a Printify shop with an Etsy shop it doesn't publish to.",
    source: "Read from Etsy and Printify",
  },
  currency: {
    title: "Currency",
    what: "The currency prices in listing files are written in. It should match your Etsy shop's currency.",
    effect: "Prices are not converted: 24.99 in a listing file is read as 24.99 in the new currency. Listings already on Etsy keep their currency.",
    source: "etsy.currency",
  },
  tier: {
    title: "How your items are made",
    what: "Print on demand fills in the three Etsy fields that describe who makes an item and when. Custom lets you set each one.",
    effect: "Applies to new listings and to listings without their own value. A listing's own file always wins.",
    source: "etsy.listing_defaults",
  },
  whoMade: {
    title: "Who made it",
    what: "Etsy's \"Who made it?\" field. For print on demand the honest answer is another company.",
    effect: "\"Another company or person\" requires a production partner, or Etsy rejects the listing.",
    source: "etsy.listing_defaults.who_made",
  },
  whenMade: {
    title: "When it was made",
    what: "Etsy's \"When was it made?\" field. Made to order means the item is produced after someone buys it.",
    effect: "A year range here would tell buyers the item already exists, which isn't true for print on demand.",
    source: "etsy.listing_defaults.when_made",
  },
  isSupply: {
    title: "What it is",
    what: "Whether the item is a finished product or a supply for making things. A printed shirt is a finished product.",
    effect: "Supplies are listed and searched separately on Etsy, so the wrong value hides listings from shoppers.",
    source: "etsy.listing_defaults.is_supply",
  },
  productionPartner: {
    title: "Production partner",
    what: "The company Etsy shows as helping make your items. It comes from the partners set up in your Etsy shop.",
    effect: "Required for print on demand, because another company makes the item. Etsy shows it to buyers on the listing.",
    source: "etsy.listing_defaults.production_partner",
  },
  renewal: {
    title: "Renewal",
    what: "Etsy listings expire after four months. Automatic renewal relists them and charges the listing fee each time.",
    effect: "Manual means expired listings stay off Etsy until you renew them.",
    source: "etsy.listing_defaults.renewal",
  },
  shippingProfile: {
    title: "Shipping profile",
    what: "Shipping prices and processing time, from the profiles in your Etsy shop.",
    effect: "Print on demand takes longer to make. A profile with a short processing time sets the wrong expectation.",
    source: "etsy.listing_defaults.shipping_profile",
  },
  returnPolicy: {
    title: "Return policy",
    what: "The return and exchange terms buyers see, from the policies in your Etsy shop.",
    effect: "Changing it updates listings the next time they are deployed.",
    source: "etsy.listing_defaults.return_policy",
  },
  printProvider: {
    title: "Preferred print provider",
    what: "The Printify printer picked first when a garment offers it. Providers differ in price, print quality and where they ship from.",
    effect: "Only new listings use it. Existing products keep their provider.",
    source: "printify.preferred_print_provider",
  },
};

/** Where "Create on …" sends you. The list re-reads when the tab regains focus. */
export const createLinks = {
  shippingProfile: { label: "Create on Etsy", href: "https://www.etsy.com/your/shops/me/tools/shipping-profiles" },
  returnPolicy: { label: "Create on Etsy", href: "https://www.etsy.com/your/shops/me/policies" },
  productionPartner: { label: "Create on Etsy", href: "https://www.etsy.com/your/shops/me/production-partners" },
  printProvider: { label: "Browse on Printify", href: "https://printify.com/app/products" },
};
