import { type RefObject, useEffect, useLayoutEffect, useRef } from "react";
import { pose, prefersReducedMotion, springBack } from "./motion";
import type { SwipeDirection } from "./swipe";
import { resist } from "./usePager";
import { useSwipe } from "./useSwipe";

/** The Lightbox's phone pager (src/ui/AGENTS.md, *Phone layout*). */

export interface CarouselOptions {
  count: number;
  index: number;
  enabled: boolean;
  onIndexChange: (index: number) => void;
}

const SETTLE_MS = 220;

function centring(direction: SwipeDirection): string {
  return direction === "left"
    ? "translateX(calc(-100% - var(--lightbox-gap)))"
    : "translateX(calc(100% + var(--lightbox-gap)))";
}

export function useCarousel(
  zone: RefObject<HTMLElement | null>,
  options: CarouselOptions,
): RefObject<HTMLDivElement | null> {
  const { count, index, enabled, onIndexChange } = options;
  const track = useRef<HTMLDivElement>(null);
  const settleTimer = useRef<number | undefined>(undefined);
  const previous = index > 0 ? index - 1 : null;
  const next = index < count - 1 ? index + 1 : null;

  useEffect(() => () => window.clearTimeout(settleTimer.current), []);

  useLayoutEffect(() => {
    window.clearTimeout(settleTimer.current);
    settleTimer.current = undefined;
    if (track.current !== null) pose(track.current, "", "");
  }, [index]);

  const targetOf = (direction: SwipeDirection | null): number | null => {
    if (direction === "left") return next;
    if (direction === "right") return previous;
    return null;
  };

  useSwipe(zone, {
    axis: "x",
    enabled,
    onDrag: (offset) => {
      const element = track.current;
      if (element === null || settleTimer.current !== undefined) return;
      const towards = offset < 0 ? next : previous;
      pose(element, `translateX(${towards === null ? resist(offset) : offset}px)`, "none");
    },
    onEnd: (direction) => {
      const element = track.current;
      if (element === null || settleTimer.current !== undefined) return;
      const target = targetOf(direction);
      if (target === null || direction === null) {
        springBack(element);
        return;
      }
      if (prefersReducedMotion()) {
        pose(element, "", "");
        onIndexChange(target);
        return;
      }
      pose(element, centring(direction), `transform ${SETTLE_MS}ms ease-out`);
      settleTimer.current = window.setTimeout(() => {
        settleTimer.current = undefined;
        onIndexChange(target);
      }, SETTLE_MS);
    },
  });

  return track;
}
