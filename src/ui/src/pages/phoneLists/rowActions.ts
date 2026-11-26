import { etsyListingUrl, printifyProductUrl } from "../../components/openOn";
import type { ListingSummary } from "../../types";
import { deleteLabel, GESTURE_LABELS, type Gesture } from "../listingLifecycle";
import type { SheetAction } from "./ActionSheet";

export function rowActions(
  row: ListingSummary,
  onGesture: (row: ListingSummary, gesture: Gesture) => void,
): SheetAction[] {
  const actions: SheetAction[] = [];
  if (row.etsy_listing_id != null) {
    actions.push({ label: "Open in Etsy", href: etsyListingUrl(row.etsy_listing_id) });
  }
  if (row.printify_product_id != null) {
    actions.push({ label: "Open in Printify", href: printifyProductUrl(row.printify_product_id) });
  }
  for (const gesture of row.gestures ?? []) {
    actions.push({
      label: gestureLabel(row, gesture),
      danger: gesture === "delete",
      onSelect: () => onGesture(row, gesture),
    });
  }
  return actions;
}

function gestureLabel(row: ListingSummary, gesture: Gesture): string {
  if (gesture === "cancel") return "Undo mark for delete";
  return gesture === "delete" ? deleteLabel(row) : GESTURE_LABELS[gesture];
}
