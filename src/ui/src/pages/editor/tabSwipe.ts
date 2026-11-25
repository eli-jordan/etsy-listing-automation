/**
 * The arithmetic behind the phone editor's tab swipe, free of the DOM.
 *
 * A finger moving left brings in the next tab (the content follows it
 * leftwards), right the previous one, the way a native pager reads.
 */

import { resist, type SwipeDirection } from "../../phone/swipe";

/** The tab a swipe moves to, or `null` at either end. */
export function neighbourTab<T>(
  tabs: readonly T[],
  current: T,
  direction: SwipeDirection,
): T | null {
  const index = tabs.indexOf(current);
  if (index < 0) return null;
  if (direction === "left") return tabs[index + 1] ?? null;
  if (direction === "right") return tabs[index - 1] ?? null;
  return null;
}

/** Which side a tab change comes in from: a later tab enters from the right. */
export function enterSide<T>(tabs: readonly T[], from: T, to: T): "left" | "right" {
  return tabs.indexOf(to) >= tabs.indexOf(from) ? "right" : "left";
}

/** How far the content follows the finger: one to one while there is a tab
 * to go to, rubber-banded past the first or the last. */
export function followOffset<T>(tabs: readonly T[], current: T, offset: number): number {
  const direction: SwipeDirection = offset < 0 ? "left" : "right";
  return neighbourTab(tabs, current, direction) === null ? resist(offset) : offset;
}
