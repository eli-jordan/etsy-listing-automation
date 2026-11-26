import { api } from "./client";
import type { MarketSnapshot } from "../types";

export class MarketApiError extends Error {}

export async function getMarketSnapshot(listing: string): Promise<MarketSnapshot | null> {
  const { data, error, response } = await api.GET("/api/listings/{name}/market", {
    params: { path: { name: listing } },
  });
  if (response.status === 404) return null;
  if (error || !data) throw new MarketApiError(`could not read the market snapshot for ${listing}`);
  return data;
}
