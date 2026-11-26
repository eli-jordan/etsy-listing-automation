import type { ListingSummary } from "../types";

let loaded: ListingSummary[] | null = null;

export function lastLoadedListings(): ListingSummary[] | null {
  return loaded;
}

export function rememberLoadedListings(listings: ListingSummary[]): void {
  loaded = listings;
}

export function resetLoadedListingsForTests(): void {
  loaded = null;
}
