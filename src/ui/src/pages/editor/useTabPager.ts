import { type RefObject, useCallback } from "react";
import { useSwipe } from "../../phone/useSwipe";
import { followOffset, neighbourTab } from "./tabSwipe";

/**
 * The phone editor's tab content as a pager: a sideways swipe on it moves to
 * the next or previous tab, the content following the finger and sliding
 * the rest of the way, exactly as tapping that tab does.
 *
 * Touch only (`useSwipe`), and only while `enabled`, which the editor ties to
 * the phone layout; anything inside that owns a sideways drag (a text field,
 * Position mode, a video's scrubber) is marked `data-swipe-ignore` and keeps
 * it.
 */

const OUT_MS = 110;
const IN_MS = 200;

function reducedMotion(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

function place(element: HTMLElement, x: string, transition: string, opacity = "") {
  element.style.transition = transition;
  element.style.transform = x === "0" ? "" : `translateX(${x})`;
  element.style.opacity = opacity;
}

/** Slides freshly shown content in from `side`. */
export function slideIn(element: HTMLElement | null, side: "left" | "right") {
  if (element === null || reducedMotion()) return;
  place(element, side === "right" ? "28%" : "-28%", "none", "0.2");
  // Reading layout commits the start position before the transition starts.
  element.getBoundingClientRect();
  place(element, "0", `transform ${IN_MS}ms ease-out, opacity ${IN_MS}ms ease-out`);
}

export function useTabPager<T>(
  panel: RefObject<HTMLElement | null>,
  {
    tabs,
    current,
    enabled,
    onPick,
  }: { tabs: readonly T[]; current: T; enabled: boolean; onPick: (tab: T) => void },
) {
  const springBack = useCallback(() => {
    if (panel.current) place(panel.current, "0", "transform 180ms ease-out");
  }, [panel]);

  useSwipe(panel, {
    axis: "x",
    enabled,
    onDrag: (offset) => {
      const element = panel.current;
      if (!element) return;
      if (offset === 0) {
        springBack();
        return;
      }
      place(element, `${followOffset(tabs, current, offset)}px`, "none");
    },
    onSwipe: (direction) => {
      const element = panel.current;
      const next = neighbourTab(tabs, current, direction);
      if (!element || next === null) {
        springBack();
        return;
      }
      if (reducedMotion()) {
        place(element, "0", "");
        onPick(next);
        return;
      }
      const out = direction === "left" ? "-28%" : "28%";
      place(element, out, `transform ${OUT_MS}ms ease-in, opacity ${OUT_MS}ms ease-in`, "0.2");
      window.setTimeout(() => onPick(next), OUT_MS);
    },
  });
}
