import type { ListingSummary } from "../types";

export type Gesture = ListingSummary["gestures"][number];

export const GESTURE_LABELS: Record<Gesture, string> = {
  delete: "Delete",
  retire: "Retire",
  "un-retire": "Un-retire",
  cancel: "Cancel",
  renew: "Renew",
};

export const MARK_FOR_DELETION_DETAILS =
  "The listing stays in this table as pending-delete. The next apply will retract the Printify product — the Etsy draft goes with it — then remove the local files. Until then you can undo the mark.";

export const DELETE_DETAILS =
  "The listing folder and its render cache are removed now. There is nothing on Printify or Etsy to retract. Designs, garment profiles and pricing plans stay.";

interface RemoteIds {
  etsy_listing_id?: number | null;
  printify_product_id?: string | null;
}

export function deleteOnlyMarks(listing: RemoteIds): boolean {
  return listing.etsy_listing_id != null || listing.printify_product_id != null;
}

export function deleteLabel(listing: RemoteIds): string {
  return deleteOnlyMarks(listing) ? "Mark for deletion" : "Delete";
}

export function deleteTitle(listing: RemoteIds & { name: string }): string {
  return deleteOnlyMarks(listing)
    ? `Are you sure you want to mark ${listing.name} for deletion?`
    : `Are you sure you want to delete ${listing.name}?`;
}

export function deleteDetails(listing: RemoteIds): string {
  return deleteOnlyMarks(listing) ? MARK_FOR_DELETION_DETAILS : DELETE_DETAILS;
}

/** What each non-delete gesture writes to `lifecycle`: `null`
 * deletes the key, which is both Un-retire and Cancel. */
export const LIFECYCLE_OF: Record<Exclude<Gesture, "delete">, "retired" | "renew" | null> = {
  retire: "retired",
  "un-retire": null,
  cancel: null,
  renew: "renew",
};
