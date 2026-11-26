import { useSyncExternalStore } from "react";

export const PHONE_LANDSCAPE_QUERY =
  "(pointer: coarse) and (orientation: landscape) and (max-height: 500px)";

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

export function useIsPhone(): boolean {
  return useMedia(PHONE_QUERY);
}

export function useIsPhoneLandscape(): boolean {
  return useMedia(PHONE_LANDSCAPE_QUERY);
}
