import { useEffect, useRef, useState } from "react";

/** Absorbs the jitter of a finger resting on the glass. */
export const FAB_SCROLL_SLOP = 8;

interface FabScroll {
  hidden: boolean;
  measuredFrom: number;
}

export function fabAfterScroll(state: FabScroll, scrollY: number): FabScroll {
  if (scrollY <= FAB_SCROLL_SLOP) return { hidden: false, measuredFrom: scrollY };
  const moved = scrollY - state.measuredFrom;
  const stillGoingTheSameWay = state.hidden ? moved > 0 : moved < 0;
  if (stillGoingTheSameWay) return { hidden: state.hidden, measuredFrom: scrollY };
  if (Math.abs(moved) < FAB_SCROLL_SLOP) return state;
  return { hidden: moved > 0, measuredFrom: scrollY };
}

export function useFabHiddenOnScroll(enabled: boolean): boolean {
  const [hidden, setHidden] = useState(false);
  const state = useRef({ hidden: false, measuredFrom: 0 });
  useEffect(() => {
    if (!enabled) return;
    state.current = { hidden: false, measuredFrom: window.scrollY };
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
