import { type Limits, type Point, type Pose, type Quad, clampPose, toUnit } from "./pose";

/**
 * What each stage handle does to a pose, given where the pointer is in photo
 * pixels. Every answer is clamped to the workspace limits, so a handle simply
 * stops at one (interactions, *Adjusting*). The pointer is taken into the
 * template box's unit frame first, where the pose lives: a homography keeps
 * straight lines straight, so the tilt handle stays on the line from the
 * box's centre to the pointer even on an angled garment.
 */

/** The corner's distance from the centre in the unit frame. */
const HALF_DIAGONAL = Math.SQRT1_2;

const centre = (pose: Pose): Point => ({ x: 0.5 + pose.offsetX, y: 0.5 + pose.offsetY });

/** Drag inside the box: the pose as it was at `start`, carried by the pointer's travel. */
export function moved(box: Quad, from: Pose, start: Point, point: Point, limits: Limits): Pose {
  const a = toUnit(box, start);
  const b = toUnit(box, point);
  return clampPose(
    { ...from, offsetX: from.offsetX + b.x - a.x, offsetY: from.offsetY + b.y - a.y },
    limits,
  );
}

/** Drag a corner: uniform scale about the box centre, by the pointer's distance from it. */
export function resized(box: Quad, from: Pose, point: Point, limits: Limits): Pose {
  const c = centre(from);
  const p = toUnit(box, point);
  return clampPose({ ...from, scale: Math.hypot(p.x - c.x, p.y - c.y) / HALF_DIAGONAL }, limits);
}

/** Drag the round handle: the top edge turns to face the pointer, in whole degrees. */
export function tilted(box: Quad, from: Pose, point: Point, limits: Limits): Pose {
  const c = centre(from);
  const p = toUnit(box, point);
  const degrees = (Math.atan2(p.y - c.y, p.x - c.x) * 180) / Math.PI + 90;
  // Into (-180, 180], so a pointer below-left reads as a large anticlockwise turn.
  const wrapped = degrees > 180 ? degrees - 360 : degrees;
  return clampPose({ ...from, rotation: Math.round(wrapped) }, limits);
}

const STEPS: Readonly<Record<string, [number, number]>> = {
  ArrowLeft: [-1, 0],
  ArrowRight: [1, 0],
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
};

/** Arrow keys move 1% of the box's width or height; with Shift, 5%. `null` for any other key. */
export function nudged(from: Pose, key: string, shift: boolean, limits: Limits): Pose | null {
  const step = STEPS[key];
  if (step === undefined) return null;
  const size = shift ? 0.05 : 0.01;
  return clampPose(
    { ...from, offsetX: from.offsetX + step[0] * size, offsetY: from.offsetY + step[1] * size },
    limits,
  );
}
