export type SwipeDirection = "left" | "right" | "up" | "down";

/** Under it, a touch is still a tap or a scroll that has not declared itself. */
export const AXIS_LOCK_PX = 10;

export const DISTANCE_PX = 64;
export const FLICK_PX = 28;
export const FLICK_PX_PER_MS = 0.45;

const AXIS_DOMINANCE = 1.2;

export function lockAxis(dx: number, dy: number): "x" | "y" | null {
  const ax = Math.abs(dx);
  const ay = Math.abs(dy);
  if (Math.max(ax, ay) < AXIS_LOCK_PX) return null;
  if (ax > ay * AXIS_DOMINANCE) return "x";
  if (ay > ax * AXIS_DOMINANCE) return "y";
  return null;
}

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
  const flick = distance >= FLICK_PX && speed >= FLICK_PX_PER_MS;
  if (!far && !flick) return null;
  if (axis === "x") return along < 0 ? "left" : "right";
  return along < 0 ? "up" : "down";
}
