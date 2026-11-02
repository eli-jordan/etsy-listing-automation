import type { ListingSummary } from "../types";

/** The listings table as it was last loaded, kept for the life of the tab so
 * returning to the page draws it at once while a fresh load runs behind it.
 * `null` until the first load: there is nothing truthful to draw before then,
 * not even "no listings". */
let loaded: ListingSummary[] | null = null;

export function lastLoadedListings(): ListingSummary[] | null {
  return loaded;
}

export function rememberLoadedListings(listings: ListingSummary[]): void {
  loaded = listings;
}

/** For tests: each one starts from a tab that has never loaded the table. */
export function forgetLoadedListings(): void {
  loaded = null;
}
