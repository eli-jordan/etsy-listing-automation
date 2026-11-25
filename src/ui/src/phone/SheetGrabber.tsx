import { type RefObject, useRef } from "react";
import { useIsPhone } from "./usePhone";
import { useSheetDrag } from "./useSheetDrag";

/**
 * The grab bar on top of a dialog that the phone layout shows as a bottom
 * sheet: pull it down and the sheet follows the finger, and a swipe down
 * dismisses it (`useSheetDrag`). Renders nothing off the phone, so a dialog
 * that includes it keeps its desktop markup exactly.
 *
 * Put it first inside the sheet element `sheetRef` points at; that element
 * is what moves.
 */
export function SheetGrabber({
  sheetRef,
  onDismiss,
}: {
  sheetRef: RefObject<HTMLElement | null>;
  onDismiss: () => void;
}) {
  const isPhone = useIsPhone();
  const zone = useRef<HTMLDivElement>(null);
  useSheetDrag(zone, { moves: sheetRef, onDismiss });

  if (!isPhone) return null;
  return (
    <div ref={zone} className="sheet-grabber" aria-hidden="true">
      <span className="sheet-grabber__bar" />
    </div>
  );
}
