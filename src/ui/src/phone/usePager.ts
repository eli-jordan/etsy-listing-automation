import { type RefObject, useEffect, useLayoutEffect, useRef } from "react";
import { pose, prefersReducedMotion, springBack } from "./motion";
import type { SwipeDirection } from "./swipe";
import { useIsPhone } from "./usePhone";
import { useSwipe } from "./useSwipe";

export interface PagerOptions<T> {
  items: readonly T[];
  current: T;
  /** Shows `item`. The pager has already slid the old one out. */
  onPick: (item: T) => void;
  enabled?: boolean;
  /** The element that moves, when it is not `zone` itself. */
  moves?: RefObject<HTMLElement | null>;
  /** How far the element follows the finger, as a share of its travel. */
  follow?: number;
}

export interface Pager<T> {
  previous: T | null;
  next: T | null;
}

const OUT_MS = 110;
const IN_MS = 200;
/** How far an item travels out and in, as a share of its own width. */
const TRAVEL_PERCENT = 28;
const OPACITY_AT_FULL_TRAVEL = "0.2";
const RESIST_RATIO = 0.35;
const RESIST_MAX_PX = 80;

/** Rubber-banding past an end, the way a native list resists being pulled
 * past its end. */
export function resist(distance: number): number {
  const sign = distance < 0 ? -1 : 1;
  return sign * Math.min(Math.abs(distance) * RESIST_RATIO, RESIST_MAX_PX);
}

function neighbour<T>(items: readonly T[], current: T, step: 1 | -1): T | null {
  const index = items.indexOf(current);
  return index < 0 ? null : (items[index + step] ?? null);
}

function slideIn(element: HTMLElement, fromRight: boolean) {
  pose(
    element,
    `translateX(${fromRight ? TRAVEL_PERCENT : -TRAVEL_PERCENT}%)`,
    "none",
    OPACITY_AT_FULL_TRAVEL,
  );
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
    const travel = direction === "left" ? -TRAVEL_PERCENT : TRAVEL_PERCENT;
    const transition = `transform ${OUT_MS}ms ease-in, opacity ${OUT_MS}ms ease-in`;
    pose(element, `translateX(${travel}%)`, transition, OPACITY_AT_FULL_TRAVEL);
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
