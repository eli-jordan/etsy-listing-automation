/** Largest-remainder apportionment: whole, nonnegative shares totaling 100.
 * Ties follow metric order. Unlike rounding then correcting the last share,
 * this never takes a percentage from a small or zero final metric.
 */
export function normalizeShares(values: number[]): number[] {
  const scale = Math.max(...values);
  const scaled = values.map((value) => value / scale);
  const total = scaled.reduce((sum, value) => sum + value, 0);
  const exact = scaled.map((value) => (value / total) * 100);
  const shares = exact.map(Math.floor);
  const order = exact
    .map((value, index) => ({ index, remainder: value - (shares[index] ?? 0) }))
    .sort((a, b) => b.remainder - a.remainder || a.index - b.index);
  const remaining = 100 - shares.reduce((sum, value) => sum + value, 0);
  for (const { index } of order.slice(0, remaining)) shares[index] = (shares[index] ?? 0) + 1;
  return shares;
}

export const METRICS = [
  { key: "reviews", label: "Reviews", hint: "Total reviews on the listing" },
  {
    key: "favourites_per_day",
    label: "Favourites per day",
    hint: "Favourites since listed, per day",
  },
  { key: "search_rank", label: "Search rank", hint: "Position in Etsy's results" },
  { key: "views_per_day", label: "Views per day", hint: "Views since listed, per day" },
  { key: "shop_sales", label: "Shop sales", hint: "The seller's total sales" },
  { key: "shop_rating", label: "Shop rating", hint: "The seller's average rating" },
] as const;

export function sharesOf(weights: Record<string, number>): number[] {
  return normalizeShares(METRICS.map(({ key }) => weights[key] ?? 0));
}

export function weightsOf(shares: number[]): Record<string, number> {
  return Object.fromEntries(METRICS.map(({ key }, index) => [key, shares[index] ?? 0]));
}
