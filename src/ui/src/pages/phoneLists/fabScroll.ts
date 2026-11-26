import { useEffect, useRef, useState } from "react";

/** How far the page must move one way before the button changes, so the
 * jitter of a finger resting on the glass does not flicker it. */
export const FAB_SCROLL_SLOP = 8;

/**
 * Whether a floating action button hides, as native lists do: it goes while
 * the list scrolls down (toward rows it would cover) and comes back on the
 * way up, and near the top it always shows.
 *
 * `anchor` is the offset the last change was measured from; the answer says
 * where to measure the next one from.
 */
export function fabAfterScroll(
  state: { hidden: boolean; anchor: number },
  scrollY: number,
): { hidden: boolean; anchor: number } {
  if (scrollY <= FAB_SCROLL_SLOP) return { hidden: false, anchor: scrollY };
  const moved = scrollY - state.anchor;
  // Moving on in the same direction carries the anchor along with it, so a
  // turn is measured from where the scroll turned.
  if (state.hidden ? moved > 0 : moved < 0) return { hidden: state.hidden, anchor: scrollY };
  if (Math.abs(moved) < FAB_SCROLL_SLOP) return state;
  return { hidden: moved > 0, anchor: scrollY };
}

export function useFabHiddenOnScroll(enabled: boolean): boolean {
  const [hidden, setHidden] = useState(false);
  const state = useRef({ hidden: false, anchor: 0 });
  useEffect(() => {
    if (!enabled) return;
    state.current = { hidden: false, anchor: window.scrollY };
    const onScroll = () => {
      state.current = fabAfterScroll(state.current, window.scrollY);
      setHidden(state.current.hidden);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      setHidden(false);
    };
  }, [enabled]);
  return enabled && hidden;
}
