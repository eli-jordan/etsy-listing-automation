import {
  type Limits,
  type Point,
  type Pose,
  type Quad,
  clampPose,
  proportions,
  toUnit,
} from "./pose";

/** The pointer relative to the posed box's centre, in rectified pixels. */
function fromCentre(box: Quad, pose: Pose, point: Point): Point {
  const { w, h } = proportions(box);
  const p = toUnit(box, point);
  return { x: (p.x - 0.5 - pose.offsetX) * w, y: (p.y - 0.5 - pose.offsetY) * h };
}

export function moved(box: Quad, from: Pose, start: Point, point: Point, limits: Limits): Pose {
  const a = toUnit(box, start);
  const b = toUnit(box, point);
  return clampPose(
    { ...from, offsetX: from.offsetX + b.x - a.x, offsetY: from.offsetY + b.y - a.y },
    limits,
  );
}

export function resized(box: Quad, from: Pose, point: Point, limits: Limits): Pose {
  // A corner sits half the rectified diagonal from the centre at scale 1.
  const { w, h } = proportions(box);
  const d = fromCentre(box, from, point);
  return clampPose({ ...from, scale: Math.hypot(d.x, d.y) / (Math.hypot(w, h) / 2) }, limits);
}

export function tilted(box: Quad, from: Pose, point: Point, limits: Limits): Pose {
  const d = fromCentre(box, from, point);
  const degrees = (Math.atan2(d.y, d.x) * 180) / Math.PI + 90;
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

/** Fractions of the box's width or height an arrow key moves it. */
const NUDGE_STEP = 0.01;
const SHIFT_NUDGE_STEP = 0.05;

/** `null` for a key that is not an arrow. */
export function nudged(from: Pose, key: string, shift: boolean, limits: Limits): Pose | null {
  const step = STEPS[key];
  if (step === undefined) return null;
  const size = shift ? SHIFT_NUDGE_STEP : NUDGE_STEP;
  return clampPose(
    { ...from, offsetX: from.offsetX + step[0] * size, offsetY: from.offsetY + step[1] * size },
    limits,
  );
}
