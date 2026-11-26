import { type RefObject, useEffect, useLayoutEffect, useRef } from "react";
import { pose, prefersReducedMotion, springBack } from "./motion";
import type { SwipeDirection } from "./swipe";
import { resist } from "./usePager";
import { useSwipe } from "./useSwipe";

/**
 * A pager laid out like a native photo viewer, for the Lightbox's pictures on
 * a phone. The neighbours sit either side of the shown item inside `track`,
 * so a finger drags the whole strip and a part-swipe shows both. Released past
 * a swipe, the strip carries on until the neighbour is centred, and only then
 * does the index move to it; short of one, it springs back. Past the first and
 * the last it resists (no wrap-around), as `usePager`'s pagers do.
 *
 * Its own hook rather than `usePager`, whose pages slide one out and the next
 * in, because only here are the neighbours on screen at once. The caller lays
 * the slides out: the previous one a track's width plus `--lightbox-gap` to
 * the left, the next one as far to the right.
 *
 * With `prefers-reduced-motion`, a swipe steps at once and nothing slides.
 */

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

  // When the index moves, the new current slide is where the neighbour was,
  // so the strip goes back to rest without a transition and nothing on
  // screen moves.
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
