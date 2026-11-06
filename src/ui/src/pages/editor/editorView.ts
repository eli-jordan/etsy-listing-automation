import { type Dispatch, type SetStateAction, useEffect, useState } from "react";

/**
 * What the seller was looking at in an editor -- the tab, the colour on the
 * stage, the picture in the preview -- kept so a page refresh comes back to it.
 *
 * In `sessionStorage` rather than the URL: the preview follows the pointer
 * across the locator, and a router navigation per hover would re-render the
 * page and run past the template editor's unsaved-edits blocker. It is per
 * browser tab, so two listings side by side keep their own views, and it is
 * never part of the document, so nothing here reaches a save.
 */

/** Which editor's view this is, or `null` for one with nothing to come back
 * to: a refresh of an unnamed draft starts a new draft. */
export type ViewScope = string | null;

export function viewScope(kind: "listing" | "listing-template", name: string): ViewScope {
  return name === "" ? null : `${kind}:${name}`;
}

export function isString(value: unknown): value is string {
  return typeof value === "string";
}

export function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

export function isNullableNumber(value: unknown): value is number | null {
  return value === null || typeof value === "number";
}

export function isBoolean(value: unknown): value is boolean {
  return typeof value === "boolean";
}

function storageKey(scope: string, slot: string): string {
  return `editor-view:${scope}:${slot}`;
}

function remembered<T>(
  scope: ViewScope,
  slot: string,
  fallback: T,
  accept: (value: unknown) => value is T,
): T {
  if (scope === null) return fallback;
  try {
    const stored = sessionStorage.getItem(storageKey(scope, slot));
    if (stored === null) return fallback;
    const value: unknown = JSON.parse(stored);
    return accept(value) ? value : fallback;
  } catch {
    // Blocked storage, or a value from an older build: the editor's default.
    return fallback;
  }
}

/**
 * `useState`, remembered under `scope` for the life of the browser tab.
 *
 * Written whenever the value *or the scope* changes, so a draft that gets its
 * name keeps the view it already has. `accept` checks what comes back, because
 * what was stored may be from an older build.
 */
export function useViewState<T>(
  scope: ViewScope,
  slot: string,
  fallback: T,
  accept: (value: unknown) => value is T,
): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => remembered(scope, slot, fallback, accept));

  useEffect(() => {
    if (scope !== null) remember(scope, slot, value);
  }, [scope, slot, value]);

  return [value, setValue];
}

function remember(scope: string, slot: string, value: unknown) {
  try {
    sessionStorage.setItem(storageKey(scope, slot), JSON.stringify(value));
  } catch {
    // Remembering is a convenience: the editor works the same without it.
  }
}

function isNumber(value: unknown): value is number {
  return typeof value === "number";
}

/** How long a refreshed page may take to grow back to where it was. */
export const SCROLL_RESTORE_MS = 5000;

/** What says the seller has taken over the scrolling themselves. */
const SCROLL_INPUTS = ["wheel", "touchstart", "keydown", "pointerdown"] as const;

/**
 * The page's scroll position, remembered under `scope` and returned to on mount.
 *
 * The browser's own restoration cannot do this: it runs when the document has
 * loaded, and at that point the listing is still being fetched, so the page is
 * too short to scroll anywhere. So this waits, a frame at a time, for the page
 * to be tall enough. Any input from the seller ends the wait, because a jump
 * under someone already scrolling is worse than not coming back at all.
 */
export function useViewScroll(scope: ViewScope) {
  useEffect(() => {
    if (scope === null) return;
    const target = remembered(scope, "scroll", 0, isNumber);
    const deadline = performance.now() + SCROLL_RESTORE_MS;
    let frame: number | null = null;

    function stopWaiting() {
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
      SCROLL_INPUTS.forEach((input) => window.removeEventListener(input, stopWaiting));
    }

    function returnWhenTallEnough() {
      const room = document.documentElement.scrollHeight - window.innerHeight;
      if (room >= target) {
        window.scrollTo(0, target);
        stopWaiting();
      } else if (performance.now() >= deadline) {
        stopWaiting();
      } else {
        frame = requestAnimationFrame(returnWhenTallEnough);
      }
    }

    function rememberScroll() {
      // Not while waiting: the page is at the top only because it is short.
      if (frame === null && scope !== null) remember(scope, "scroll", window.scrollY);
    }

    if (target > 0) {
      SCROLL_INPUTS.forEach((input) =>
        window.addEventListener(input, stopWaiting, { passive: true }),
      );
      frame = requestAnimationFrame(returnWhenTallEnough);
    }
    window.addEventListener("scroll", rememberScroll, { passive: true });
    return () => {
      stopWaiting();
      window.removeEventListener("scroll", rememberScroll);
    };
  }, [scope]);
}
