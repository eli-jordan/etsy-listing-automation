import { type RefObject, useEffect } from "react";

export function useModalKeys(dialog: RefObject<HTMLElement | null>, onCancel: () => void) {
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCancel();
        return;
      }
      if (event.key !== "Tab" || !dialog.current) return;
      const focusable = [
        ...dialog.current.querySelectorAll<HTMLElement>("button, select, input, a[href]"),
      ].filter((el) => !el.hasAttribute("disabled"));
      if (focusable.length === 0) return;
      const at = focusable.indexOf(document.activeElement as HTMLElement);
      const next = nextFocus(at, focusable.length, event.shiftKey);
      event.preventDefault();
      focusable[next]?.focus();
    };
    // Clicking non-focusable modal content can leave focus on body. Capture
    // Tab on window so the next key still stays inside the dialog.
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [dialog, onCancel]);
}

function nextFocus(at: number, count: number, backwards: boolean): number {
  if (at < 0) return backwards ? count - 1 : 0;
  return (at + (backwards ? -1 : 1) + count) % count;
}
