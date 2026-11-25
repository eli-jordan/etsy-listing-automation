import { type RefObject, useRef } from "react";
import { useIsPhone } from "./usePhone";
import { usePhoneModal } from "./usePhoneModal";
import { useSheetDrag } from "./useSheetDrag";

/**
 * The grab bar on top of a dialog that the phone layout shows as a bottom
 * sheet: pull it down and the sheet follows the finger, and a swipe down
 * dismisses it (`useSheetDrag`). Renders nothing off the phone, so a dialog
 * that includes it keeps its desktop markup exactly.
 *
 * Put it first inside the sheet element `sheetRef` points at; that element
 * is what moves. `head` makes the sheet's head (its title row) a drag zone
 * too, as a native sheet's is; a button in it still taps.
 *
 * It also makes the sheet modal on the phone (`usePhoneModal`): the page
 * behind stops scrolling, focus moves in and stays, and Back closes it. A
 * sheet that must not be dismissed for now passes a null `onDismiss`: it
 * keeps the modal behaviour but shows no grab bar.
 */
export function SheetGrabber({
  sheetRef,
  onDismiss,
  head,
}: {
  sheetRef: RefObject<HTMLElement | null>;
  onDismiss: (() => void) | null;
  head?: RefObject<HTMLElement | null>;
}) {
  const isPhone = useIsPhone();
  const zone = useRef<HTMLDivElement>(null);
  const noHead = useRef<HTMLElement>(null);
  const dismiss = onDismiss ?? (() => {});
  usePhoneModal(sheetRef, { onClose: onDismiss });
  useSheetDrag(zone, { moves: sheetRef, onDismiss: dismiss, enabled: onDismiss !== null });
  useSheetDrag(head ?? noHead, {
    moves: sheetRef,
    onDismiss: dismiss,
    enabled: onDismiss !== null && head !== undefined,
  });

  if (!isPhone || onDismiss === null) return null;
  return (
    <div ref={zone} className="sheet-grabber" aria-hidden="true">
      <span className="sheet-grabber__bar" />
    </div>
  );
}
