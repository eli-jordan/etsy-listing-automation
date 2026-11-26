import { type Dispatch, type SetStateAction, useEffect, useState } from "react";

export type ViewScope = string | null;

export function viewScope(kind: "listing" | "listing-template", name: string): ViewScope {
  return name === "" ? null : `${kind}:${name}`;
}

export function isString(value: unknown): value is string {
  return typeof value === "string";
}

export function isStringList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isString);
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
    // Storage may refuse the write (blocked, or full).
  }
}

function isNumber(value: unknown): value is number {
  return typeof value === "number";
}

export const SCROLL_RESTORE_MS = 5000;

const USER_SCROLL_INPUTS = ["wheel", "touchstart", "keydown", "pointerdown"] as const;

/** The browser restores scroll at load, while the listing is still being fetched and the page
 * is too short, so this waits a frame at a time for the page to grow. */
export function useViewScroll(scope: ViewScope) {
  useEffect(() => {
    if (scope === null) return;
    const target = remembered(scope, "scroll", 0, isNumber);
    const deadline = performance.now() + SCROLL_RESTORE_MS;
    let frame: number | null = null;

    function stopWaiting() {
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
      USER_SCROLL_INPUTS.forEach((input) => window.removeEventListener(input, stopWaiting));
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
      if (frame === null && scope !== null) remember(scope, "scroll", window.scrollY);
    }

    if (target > 0) {
      USER_SCROLL_INPUTS.forEach((input) =>
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
