export function hasOpenTargets(
  etsyListingId: number | null | undefined,
  printifyProductId: string | null | undefined,
): boolean {
  return (
    (etsyListingId !== null && etsyListingId !== undefined) ||
    (printifyProductId !== null && printifyProductId !== undefined)
  );
}

/** Shop Manager's editor, not the public listing page: a listing this tool
 * creates stays an Etsy draft, whose public URL 404s. */
export function etsyListingUrl(listingId: number): string {
  return `https://www.etsy.com/your/shops/me/listing-editor/edit/${listingId}`;
}

export function printifyProductUrl(productId: string): string {
  return `https://printify.com/app/product-details/${encodeURIComponent(productId)}`;
}
