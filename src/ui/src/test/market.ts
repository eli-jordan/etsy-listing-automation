import type { MarketSnapshot, ScoredListing } from "../types";

/**
 * Market snapshots as `GET /api/listings/{name}/market` and the run's
 * `market` event carry them, for the top listings panel's tests.
 */

export function scoredListing(id: number, over: Partial<ScoredListing> = {}): ScoredListing {
  return {
    listing_id: id,
    rank: id,
    score_raw: (95 - id) / 100,
    score: 95 - id,
    title: `Retro Sunset Hiking Shirt ${id}`,
    url: `https://www.etsy.com/listing/${id}/retro-sunset`,
    shop_id: 70 + id,
    shop_name: `TrailTees${id}`,
    own_shop: false,
    thumbnail_url: `https://i.etsystatic.com/${id}/il_170x135.jpg`,
    search_rank: id,
    reviews: 10 * id,
    favourites_per_day: 1.5,
    views_per_day: 12,
    shop_sales: 500,
    shop_rating: 4.8,
    tags: ["hiking shirt", "retro sunset"],
    lead: "A retro sunset over the peaks.",
    ...over,
  };
}

export const MARKET_QUERIES = [
  "retro sunset hiking shirt",
  "take a hike t shirt",
  "vintage mountain graphic tee",
];

/** A finished search: `scored` listings (12 by default, so four sit past
 * the top eight) and three phrases. `edit` changes listings by rank. */
export function marketSnapshot({
  edit = {},
  ...over
}: Partial<MarketSnapshot> & {
  edit?: Record<number, Partial<ScoredListing>>;
} = {}): MarketSnapshot {
  const scored = over.scored ?? 12;
  const listings = Array.from({ length: scored }, (_, i) => scoredListing(i + 1, edit[i + 1]));
  return {
    queries: MARKET_QUERIES,
    found: 58,
    scored,
    searched_at: new Date().toISOString(),
    listings,
    phrases: [
      { phrase: "retro hiking shirt", listings: 12, score: 1 },
      { phrase: "Hiker Gift", listings: 9, score: 0.8 },
      { phrase: "mountain sunset", listings: 4, score: 0.4 },
    ],
    relaxed: false,
    empty: scored === 0,
    block: "",
    ...over,
  };
}
