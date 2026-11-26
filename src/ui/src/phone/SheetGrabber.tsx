import { type RefObject, useRef } from "react";
import { useIsPhone } from "./usePhone";
import { usePhoneModal } from "./usePhoneModal";
import { useSheetDrag } from "./useSheetDrag";

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
