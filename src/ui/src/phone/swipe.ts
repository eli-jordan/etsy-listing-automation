/**
 * The gesture arithmetic behind the phone's swipes, kept free of the DOM so
 * the thresholds are tested on numbers rather than synthetic touches.
 */

export type SwipeDirection = "left" | "right" | "up" | "down";

/** How far a finger must travel before a direction is locked in. Under it,
 * a touch is still a tap or a scroll that has not declared itself. */
export const AXIS_LOCK_PX = 10;

/** A swipe is a deliberate horizontal (or vertical) move: either far enough,
 * or a quick flick that is still more than a twitch. */
export const DISTANCE_PX = 64;
export const FLICK_PX = 28;
export const FLICK_SPEED = 0.45; // px per ms

/** The axis a move has committed to, or null while it is still too small,
 * or too diagonal, to say. A move must be clearly more along one axis than
 * the other, so a slightly slanted scroll never turns into a swipe. */
export function lockAxis(dx: number, dy: number): "x" | "y" | null {
  const ax = Math.abs(dx);
  const ay = Math.abs(dy);
  if (Math.max(ax, ay) < AXIS_LOCK_PX) return null;
  if (ax > ay * 1.2) return "x";
  if (ay > ax * 1.2) return "y";
  return null;
}

/** The swipe a finished move was, if it was one at all. */
export function classifySwipe(
  dx: number,
  dy: number,
  ms: number,
  axis: "x" | "y" | null,
): SwipeDirection | null {
  if (axis === null) return null;
  const along = axis === "x" ? dx : dy;
  const distance = Math.abs(along);
  const speed = distance / Math.max(ms, 1);
  const far = distance >= DISTANCE_PX;
  const flick = distance >= FLICK_PX && speed >= FLICK_SPEED;
  if (!far && !flick) return null;
  if (axis === "x") return along < 0 ? "left" : "right";
  return along < 0 ? "up" : "down";
}

/** Rubber-banding past an edge: the further the drag, the less it moves, the
 * way a native list resists being pulled past its end. */
export function resist(distance: number): number {
  const sign = distance < 0 ? -1 : 1;
  return sign * Math.min(Math.abs(distance) * 0.35, 80);
}
