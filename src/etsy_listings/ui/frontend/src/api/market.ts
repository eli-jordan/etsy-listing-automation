import { api } from "./client";
import type { MarketSnapshot } from "../types";

/**
 * A listing's latest market research (market-seo.md, *Cache*), which the top
 * listings panel reads on mount so a reload shows the last search again.
 */

export class MarketApiError extends Error {}

/** The snapshot, or `null` before the listing's first search. */
export async function getMarketSnapshot(listing: string): Promise<MarketSnapshot | null> {
  const { data, error, response } = await api.GET("/api/listings/{name}/market", {
    params: { path: { name: listing } },
  });
  if (response.status === 404) return null;
  if (error || !data) throw new MarketApiError(`could not read the market snapshot for ${listing}`);
  return data;
}
