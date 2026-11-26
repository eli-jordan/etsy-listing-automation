import { type RefObject, useEffect, useEffectEvent } from "react";
import { pushSheetEntry } from "./sheetHistory";
import { useIsPhone } from "./usePhone";

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [contenteditable="true"], [tabindex]:not([tabindex="-1"])';

/** The open sheets, the newest last: only the top one keeps Tab. */
const stack: HTMLElement[] = [];

let locks = 0;
let unlockTo: { overflow: string; x: number; y: number } | null = null;

function lockPageScroll(): () => void {
  if (locks === 0) {
    unlockTo = { overflow: document.body.style.overflow, x: window.scrollX, y: window.scrollY };
    document.body.style.overflow = "hidden";
  }
  locks += 1;
  return () => {
    locks -= 1;
    if (locks > 0 || unlockTo === null) return;
    const { overflow, x, y } = unlockTo;
    unlockTo = null;
    document.body.style.overflow = overflow;
    if (window.scrollX !== x || window.scrollY !== y) window.scrollTo(x, y);
  };
}

function focusables(box: HTMLElement): HTMLElement[] {
  return [...box.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
    (element) => element.closest("[hidden], [inert]") === null,
  );
}

export function usePhoneModal(
  box: RefObject<HTMLElement | null>,
  { onClose }: { onClose: (() => void) | null },
): void {
  const isPhone = useIsPhone();
  const dismissible = onClose !== null;
  const close = useEffectEvent(() => onClose?.());

  useEffect(() => {
    const element = box.current;
    if (!isPhone || element === null) return;
    const unlock = lockPageScroll();
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    stack.push(element);
    element.setAttribute("data-phone-sheet", "");
    if (!element.contains(document.activeElement)) {
      if (!element.hasAttribute("tabindex")) element.setAttribute("tabindex", "-1");
      element.focus({ preventScroll: true });
    }

    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Tab" || event.defaultPrevented) return;
      if (stack[stack.length - 1] !== element) return;
      const inside = focusables(element);
      const first = inside[0];
      const last = inside[inside.length - 1];
      const active = document.activeElement;
      if (first === undefined || last === undefined) {
        event.preventDefault();
        element.focus({ preventScroll: true });
      } else if (!element.contains(active) || active === element) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);

    return () => {
      document.removeEventListener("keydown", onKey);
      const at = stack.indexOf(element);
      if (at >= 0) stack.splice(at, 1);
      element.removeAttribute("data-phone-sheet");
      unlock();
      // Back to the opener, unless the sheet handed focus on to something
      // else (a dialog that followed it, a field on the next page).
      const active = document.activeElement;
      const lost = active === null || active === document.body || element.contains(active);
      if (lost && opener?.isConnected) opener.focus({ preventScroll: true });
    };
  }, [isPhone, box]);

  useEffect(() => {
    if (!isPhone || !dismissible) return;
    return pushSheetEntry(close);
  }, [isPhone, dismissible]);
}
