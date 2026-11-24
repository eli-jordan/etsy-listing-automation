import { useSyncExternalStore } from "react";

/**
 * The phone layout's one breakpoint. Every rule in `phone/*.css` sits inside
 * this query, and every phone-only behaviour asks `useIsPhone`, so the
 * desktop layout (anything wider) is untouched by construction.
 */
export const PHONE_QUERY = "(max-width: 700px)";

function phoneQuery(): MediaQueryList | null {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return null;
  return window.matchMedia(PHONE_QUERY);
}

function subscribe(onChange: () => void): () => void {
  const query = phoneQuery();
  if (!query) return () => {};
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

function snapshot(): boolean {
  return phoneQuery()?.matches ?? false;
}

/** Whether the phone layout is showing. False wherever `matchMedia` is
 * missing (jsdom, old browsers), so tests and desktop see one DOM. */
export function useIsPhone(): boolean {
  return useSyncExternalStore(subscribe, snapshot, () => false);
}
