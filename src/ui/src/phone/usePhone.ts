import { useSyncExternalStore } from "react";

/**
 * A phone on its side: wider than 700px, so it needs its own clause, but
 * short and driven by a finger. `pointer: coarse` keeps a short desktop
 * window (a mouse) on the desktop layout.
 */
export const PHONE_LANDSCAPE_QUERY =
  "(pointer: coarse) and (orientation: landscape) and (max-height: 500px)";

/**
 * The phone layout's one breakpoint: a narrow window, or a phone held
 * sideways. Every rule in `phone/*.css` sits inside this query (phoneQuery
 * .test.ts holds the stylesheets to it), and every phone-only behaviour asks
 * `useIsPhone`, so the desktop layout is untouched by construction.
 */
export const PHONE_QUERY = `(max-width: 700px), ${PHONE_LANDSCAPE_QUERY}`;

function mediaQuery(query: string): MediaQueryList | null {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return null;
  return window.matchMedia(query);
}

function useMedia(query: string): boolean {
  const subscribe = (onChange: () => void) => {
    const list = mediaQuery(query);
    if (!list) return () => {};
    list.addEventListener("change", onChange);
    return () => list.removeEventListener("change", onChange);
  };
  return useSyncExternalStore(
    subscribe,
    () => mediaQuery(query)?.matches ?? false,
    () => false,
  );
}

/** Whether the phone layout is showing. False wherever `matchMedia` is
 * missing (jsdom, old browsers), so tests and desktop see one DOM. */
export function useIsPhone(): boolean {
  return useMedia(PHONE_QUERY);
}

/** Whether the phone layout is showing on a phone held sideways. */
export function useIsPhoneLandscape(): boolean {
  return useMedia(PHONE_LANDSCAPE_QUERY);
}
