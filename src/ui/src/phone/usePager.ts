import { type RefObject, useEffect, useLayoutEffect, useRef } from "react";
import { pose, prefersReducedMotion, springBack } from "./motion";
import type { SwipeDirection } from "./swipe";
import { useIsPhone } from "./usePhone";
import { useSwipe } from "./useSwipe";

/**
 * A sideways pager for the phone layout: a swipe left on `zone` picks the
 * item after `current`, a swipe right the one before, the way a native pager
 * reads. Every phone pager -- the editor's tabs, Admin's sections, the
 * template switcher, the Lightbox's pictures -- goes through here, so they
 * all feel the same:
 *
 * - The moving element follows the finger one to one while there is an item
 *   to go to, and resists past the first or the last (no wrap-around, so the
 *   ends read as ends).
 * - A swipe slides it out towards the finger in 110ms, then picks; whenever
 *   `current` changes, by a swipe or a tap elsewhere, the new item slides in
 *   from its side over 200ms. A release short of a swipe springs back.
 * - With `prefers-reduced-motion`, a swipe picks at once and nothing slides.
 *
 * Phone only, and a finger only: off the phone layout nothing listens and
 * nothing moves, so a desktop page that mounts it keeps its DOM and styles.
 * Anything inside that owns a sideways drag (a slider, a sideways scroller,
 * the field being typed in, `data-swipe-ignore`) keeps it.
 */

export interface PagerOptions<T> {
  /** Every item, in the order the swipes walk. */
  items: readonly T[];
  current: T;
  /** Shows `item`. The pager has already slid the old one out. */
  onPick: (item: T) => void;
  /** Off for a while on the phone too (the Lightbox at 1:1, where a finger
   * pans the picture). */
  enabled?: boolean;
  /** The element that moves, when it is not `zone` itself. */
  moves?: RefObject<HTMLElement | null>;
  /** How far the element follows the finger, as a share of its travel. */
  follow?: number;
}

export interface Pager<T> {
  /** The neighbours a swipe would pick, null at an end, for arrows beside
   * the pager. */
  previous: T | null;
  next: T | null;
}

const OUT_MS = 110;
const IN_MS = 200;
/** How far an item travels out and in, as a share of its own width. */
const TRAVEL = 28;
/** How faint an item is at the far end of its travel. */
const DIM = "0.2";

/** Rubber-banding past an end: the further the drag, the less it moves, the
 * way a native list resists being pulled past its end. */
export function resist(distance: number): number {
  const sign = distance < 0 ? -1 : 1;
  return sign * Math.min(Math.abs(distance) * 0.35, 80);
}

function neighbour<T>(items: readonly T[], current: T, step: 1 | -1): T | null {
  const index = items.indexOf(current);
  return index < 0 ? null : (items[index + step] ?? null);
}

function slideIn(element: HTMLElement, fromRight: boolean) {
  pose(element, `translateX(${fromRight ? TRAVEL : -TRAVEL}%)`, "none", DIM);
  // Reading layout commits the start position before the transition starts.
  element.getBoundingClientRect();
  pose(element, "", `transform ${IN_MS}ms ease-out, opacity ${IN_MS}ms ease-out`);
}

export function usePager<T>(
  zone: RefObject<HTMLElement | null>,
  options: PagerOptions<T>,
): Pager<T> {
  const { items, current, onPick, follow = 1 } = options;
  const isPhone = useIsPhone();
  const enabled = isPhone && (options.enabled ?? true);
  const moves = options.moves ?? zone;
  const previous = neighbour(items, current, -1);
  const next = neighbour(items, current, 1);
  const shown = useRef(current);
  /** Slid out and waiting for `current` to change; a pick the caller
   * refused would otherwise leave the element off to one side. */
  const away = useRef(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  useLayoutEffect(() => {
    const from = shown.current;
    shown.current = current;
    away.current = false;
    const element = moves.current;
    if (from === current || !enabled || element === null || prefersReducedMotion()) return;
    slideIn(element, items.indexOf(current) >= items.indexOf(from));
  }, [current, enabled, items, moves]);

  const leave = (element: HTMLElement, target: T, direction: SwipeDirection) => {
    const travel = direction === "left" ? -TRAVEL : TRAVEL;
    const transition = `transform ${OUT_MS}ms ease-in, opacity ${OUT_MS}ms ease-in`;
    pose(element, `translateX(${travel}%)`, transition, DIM);
    away.current = true;
    timer.current = window.setTimeout(() => {
      onPick(target);
      timer.current = window.setTimeout(() => {
        if (away.current) springBack(element);
      }, IN_MS);
    }, OUT_MS);
  };

  const targetOf = (direction: SwipeDirection | null): T | null => {
    if (direction === "left") return next;
    if (direction === "right") return previous;
    return null;
  };

  useSwipe(zone, {
    axis: "x",
    enabled,
    onDrag: (offset) => {
      const element = moves.current;
      if (element === null) return;
      const towards = offset < 0 ? next : previous;
      const along = towards === null ? resist(offset) : offset;
      pose(element, `translateX(${along * follow}px)`, "none");
    },
    onEnd: (direction) => {
      const element = moves.current;
      const target = targetOf(direction);
      if (element === null) return;
      if (target === null || direction === null) {
        springBack(element);
      } else if (prefersReducedMotion()) {
        pose(element, "", "");
        onPick(target);
      } else {
        leave(element, target, direction);
      }
    },
  });

  return { previous, next };
}
