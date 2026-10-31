import type { ReturnPolicyTerms, ShopChanges, ShopSettings } from "../../api/shop";

/**
 * The Shop tab's vocabulary: Etsy's enumerations as the page labels them,
 * the Print on demand derivation, and every info card's copy. Etsy's
 * `who_made` and `when_made` values come from `updateListing` in the Open
 * API reference (checked 2026-10-30); a saved value outside them is still
 * shown, never replaced.
 */

export interface Option {
  value: string;
  label: string;
}

export const WHO_MADE: Option[] = [
  { value: "i_did", label: "I did" },
  { value: "collective", label: "A member of my shop" },
  { value: "someone_else", label: "Another company or person" },
];

const ERAS = [
  "2020_2026",
  "2010_2019",
  "2007_2009",
  "before_2007",
  "2000_2006",
  "1990s",
  "1980s",
  "1970s",
  "1960s",
  "1950s",
  "1940s",
  "1930s",
  "1920s",
  "1910s",
  "1900s",
  "1800s",
  "1700s",
  "before_1700",
];

export const WHEN_MADE: Option[] = [
  { value: "made_to_order", label: "Made to order" },
  ...ERAS.map((era) => ({
    value: era,
    label: era.replace("before_", "Before ").replace("_", " – "),
  })),
];

export const IS_SUPPLY: Option[] = [
  { value: "false", label: "A finished product" },
  { value: "true", label: "A craft supply or tool" },
];

export const RENEWAL: Option[] = [
  { value: "manual", label: "Manual" },
  { value: "auto", label: "Automatic" },
];

/** What Print on demand writes, together, in one save. There is no stored
 * preset: these three values *are* Print on demand (Admin plan, *Shop*). */
export const PRINT_ON_DEMAND = {
  who_made: "someone_else",
  when_made: "made_to_order",
  is_supply: false,
} satisfies ShopChanges;

export function isPrintOnDemand(defaults: ShopSettings["listing_defaults"]): boolean {
  return (
    defaults.who_made === PRINT_ON_DEMAND.who_made &&
    defaults.when_made === PRINT_ON_DEMAND.when_made &&
    defaults.is_supply === PRINT_ON_DEMAND.is_supply
  );
}

export function labelOf(options: Option[], value: string): string {
  return options.find((o) => o.value === value)?.label ?? value;
}

/** A return policy's identity as a select value: Etsy gives it no title. */
export function policyKey(terms: ReturnPolicyTerms | null | undefined): string {
  if (!terms) return "";
  return `${terms.accepts_returns}/${terms.accepts_exchanges}/${terms.within_days ?? ""}`;
}

/** The same words `ReturnPolicy.describe()` uses server-side, for a saved
 * policy the lookup did not return. */
export function describeTerms(terms: ReturnPolicyTerms): string {
  const accepted = [
    terms.accepts_returns ? "returns" : null,
    terms.accepts_exchanges ? "exchanges" : null,
  ].filter(Boolean);
  if (accepted.length === 0) return "no returns or exchanges";
  const within = terms.within_days ? ` within ${terms.within_days} days` : "";
  return `${accepted.join(" and ")}${within}`;
}

export type Creatable =
  "production_partner" | "preferred_print_provider" | "shipping_profile" | "return_policy";

/** Where Create/Browse sends the seller. The list re-reads when this tab
 * regains focus; nothing here can create the item itself.
 *
 * Each Etsy URL is the one Etsy's own help article links to, checked
 * 2026-10-30: shipping profiles in "How to Set Up Shipping Information"
 * (help.etsy.com/hc/articles/115014115187), return policies under Policy
 * settings in "How do I Set Return Policies on My Listings"
 * (help.etsy.com/hc/articles/7869401615255), and "Partners you work with"
 * in "Working with Production Partners on Etsy"
 * (help.etsy.com/hc/articles/360000336547). */
export const CREATE_LINKS: Record<Creatable, { label: string; href: string; where: string }> = {
  shipping_profile: {
    label: "Create on Etsy",
    href: "https://www.etsy.com/your/shops/me/tools/shipping-profiles",
    where: "Etsy",
  },
  return_policy: {
    label: "Create on Etsy",
    href: "https://www.etsy.com/your/shops/me/shop-policies",
    where: "Etsy",
  },
  production_partner: {
    label: "Create on Etsy",
    href: "https://www.etsy.com/your/shops/me/production-partners",
    where: "Etsy",
  },
  preferred_print_provider: {
    label: "Browse on Printify",
    href: "https://printify.com/app/products",
    where: "Printify",
  },
};

export interface InfoCopy {
  title: string;
  what: string;
  effect: string;
  /** Where the value lives: a shop.yaml key, or "Read from …". */
  source: string;
}

export const INFO: Record<string, InfoCopy> = {
  etsyShop: {
    title: "Etsy shop",
    what: "The shop every listing deploys to. It is the shop owned by the Etsy account you signed in with.",
    effect:
      "Read-only here. Sign in with `etsy-listings auth etsy` and run `etsy-listings setup` to change it.",
    source: "etsy.shop_name, etsy.shop_id",
  },
  printifyShop: {
    title: "Printify shop",
    what: "Where products are created and published from.",
    effect:
      "Read-only here. Connect with `etsy-listings auth printify` and run `etsy-listings setup` to change it.",
    source: "printify.shop_name, printify.shop_id",
  },
  currency: {
    title: "Currency",
    what: "The currency every price in this workspace is written in. It should match your Etsy shop's currency.",
    effect:
      "Nothing is converted. Saved prices keep the currency written beside them and may need re-pricing before they deploy again. Listings already on Etsy keep their currency.",
    source: "etsy.currency",
  },
  tier: {
    title: "How your items are made",
    what: "Print on demand fills in the three Etsy fields that describe who makes an item and when. Custom lets you set each one.",
    effect:
      "Applies to new listings and to listings without their own value. A listing's own file always wins.",
    source: "etsy.listing_defaults",
  },
  who_made: {
    title: "Who made it",
    what: 'Etsy\'s "Who made it?" field. For print on demand the honest answer is another company.',
    effect:
      '"Another company or person" requires a production partner, or Etsy rejects the listing.',
    source: "etsy.listing_defaults.who_made",
  },
  when_made: {
    title: "When it was made",
    what: 'Etsy\'s "When was it made?" field. Made to order means the item is produced after someone buys it.',
    effect:
      "A year range here would tell buyers the item already exists, which isn't true for print on demand.",
    source: "etsy.listing_defaults.when_made",
  },
  is_supply: {
    title: "What it is",
    what: "Whether the item is a finished product or a supply for making things. A printed shirt is a finished product.",
    effect:
      "Supplies are listed and searched separately on Etsy, so the wrong value hides listings from shoppers.",
    source: "etsy.listing_defaults.is_supply",
  },
  production_partner: {
    title: "Production partner",
    what: "The company Etsy shows as helping make your items. It comes from the partners set up in your Etsy shop.",
    effect:
      "Required for print on demand, because another company makes the item. Etsy shows it to buyers on the listing.",
    source: "etsy.listing_defaults.production_partner",
  },
  renewal: {
    title: "Renewal",
    what: "Etsy listings expire after four months. Automatic renewal relists them and charges the listing fee each time.",
    effect: "Manual means expired listings stay off Etsy until you renew them.",
    source: "etsy.listing_defaults.renewal",
  },
  shipping_profile: {
    title: "Shipping profile",
    what: "Shipping prices and processing time, from the profiles in your Etsy shop.",
    effect:
      "Print on demand takes longer to make. A profile with a short processing time sets the wrong expectation.",
    source: "etsy.listing_defaults.shipping_profile",
  },
  return_policy: {
    title: "Return policy",
    what: "The return and exchange terms buyers see, from the policies in your Etsy shop.",
    effect: "Listings without their own policy use it the next time they are deployed.",
    source: "etsy.listing_defaults.return_policy",
  },
  preferred_print_provider: {
    title: "Preferred print provider",
    what: "The Printify printer `new` picks first when the chosen garment offers it. Providers differ in price, print quality and where they ship from.",
    effect: "Only new listings use it. Existing products keep their provider.",
    source: "printify.preferred_print_provider",
  },
};
