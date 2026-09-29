/** The delete confirmation's words for a listing template, shared by the two
 * places that offer Delete: its card on the Listing templates page and the
 * template editor's action row (UI doc §2, §3). */
export const TEMPLATE_DELETE_DETAILS =
  "The listing template's folder and its own files are removed. Batches and listings made from it are unaffected: they keep their own copies.";

export function templateDeleteTitle(name: string): string {
  return `Delete ${name}?`;
}
