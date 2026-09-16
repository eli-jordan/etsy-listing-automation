/**
 * Where "Open on Etsy" and "Open on Printify" actually go.
 *
 * Beside `OpenOnMenu` rather than inside it because the listings table asks
 * the same question the menu does -- is there anything to open -- before it
 * decides whether to render the menu at all, and a component file that also
 * exports plain functions is a file Vite cannot hot-reload.
 */

/** Whether this menu has anything to show. Exported because the two callers
 * decide for themselves whether an empty menu is worth rendering, and an
 * absent id arrives as `null` from the API and `undefined` from a partial
 * fixture -- one predicate so the two cannot be told apart differently in two
 * places. */
export function hasOpenTargets(
  etsyListingId: number | null | undefined,
  printifyProductId: string | null | undefined,
): boolean {
  return (
    (etsyListingId !== null && etsyListingId !== undefined) ||
    (printifyProductId !== null && printifyProductId !== undefined)
  );
}

export function etsyListingUrl(listingId: number): string {
  return `https://www.etsy.com/your/shops/me/listing-editor/edit/${listingId}`;
}

export function printifyProductUrl(productId: string): string {
  return `https://printify.com/app/product-details/${encodeURIComponent(productId)}`;
}
