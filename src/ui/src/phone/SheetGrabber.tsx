import { type RefObject, useRef } from "react";
import { useIsPhone } from "./usePhone";
import { useSwipe } from "./useSwipe";

/**
 * The grab bar on top of a dialog that the phone layout shows as a bottom
 * sheet: pull it down and the sheet follows the finger, and a swipe down
 * dismisses it. Renders nothing off the phone, so a dialog that includes it
 * keeps its desktop markup exactly.
 *
 * Put it first inside the sheet element `sheetRef` points at; that element
 * is what moves.
 */

const OUT_MS = 180;

function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export function SheetGrabber({
  sheetRef,
  onDismiss,
}: {
  sheetRef: RefObject<HTMLElement | null>;
  onDismiss: () => void;
}) {
  const isPhone = useIsPhone();
  const zone = useRef<HTMLDivElement>(null);

  useSwipe(zone, {
    axis: "y",
    enabled: isPhone,
    onDrag: (offset) => {
      const sheet = sheetRef.current;
      if (!sheet) return;
      // Up does nothing: a sheet only ever leaves downwards.
      sheet.style.transition = offset ? "none" : "";
      sheet.style.transform = offset > 0 ? `translateY(${offset}px)` : "";
    },
    onSwipe: (direction) => {
      const sheet = sheetRef.current;
      if (direction !== "down" || !sheet) {
        if (sheet) {
          sheet.style.transition = "";
          sheet.style.transform = "";
        }
        return;
      }
      if (prefersReducedMotion()) {
        onDismiss();
        return;
      }
      sheet.style.transition = `transform ${OUT_MS}ms ease-in`;
      sheet.style.transform = "translateY(100%)";
      window.setTimeout(onDismiss, OUT_MS);
    },
  });

  if (!isPhone) return null;
  return (
    <div ref={zone} className="sheet-grabber" aria-hidden="true">
      <span className="sheet-grabber__bar" />
    </div>
  );
}
