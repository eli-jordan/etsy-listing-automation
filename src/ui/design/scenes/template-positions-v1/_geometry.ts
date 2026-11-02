/**
 * A listing position as the editor thinks of it: the template box moved,
 * scaled and turned in its own frame. The spec stores absolute corners; the
 * pose is what the handles edit and what the limits check.
 */
export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Pose {
  scale: number;
  /** Fractions of the template box's width and height. */
  dx: number;
  dy: number;
  /** Degrees, clockwise. */
  rotation: number;
}

export interface Bounds {
  scaleMin: number;
  scaleMax: number;
  offset: number;
  rotation: number;
}

const clampTo = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export function clampPose(p: Pose, b: Bounds): Pose {
  return {
    scale: clampTo(p.scale, b.scaleMin, b.scaleMax),
    dx: clampTo(p.dx, -b.offset, b.offset),
    dy: clampTo(p.dy, -b.offset, b.offset),
    rotation: clampTo(p.rotation, -b.rotation, b.rotation),
  };
}

export type Part = "scale" | "dx" | "dy" | "rotation";

/** Which parts sit on a limit (within rounding). */
export function partsAtLimit(p: Pose, b: Bounds): Set<Part> {
  const at = new Set<Part>();
  const near = (v: number, edge: number) => Math.abs(v - edge) < 1e-3;
  if (near(p.scale, b.scaleMin) || near(p.scale, b.scaleMax)) at.add("scale");
  if (near(Math.abs(p.dx), b.offset)) at.add("dx");
  if (near(Math.abs(p.dy), b.offset)) at.add("dy");
  if (near(Math.abs(p.rotation), b.rotation)) at.add("rotation");
  return at;
}

export function outOfRange(p: Pose, b: Bounds): Set<Part> {
  const out = new Set<Part>();
  if (p.scale < b.scaleMin - 1e-6 || p.scale > b.scaleMax + 1e-6) out.add("scale");
  if (Math.abs(p.dx) > b.offset + 1e-6) out.add("dx");
  if (Math.abs(p.dy) > b.offset + 1e-6) out.add("dy");
  if (Math.abs(p.rotation) > b.rotation + 1e-6) out.add("rotation");
  return out;
}

export const isIdentity = (p: Pose) =>
  Math.abs(p.scale - 1) < 1e-6 && p.dx === 0 && p.dy === 0 && p.rotation === 0;

/** Box centre after the pose's offset, in photo pixels. */
export const centreOf = (box: Rect, p: Pose) => ({
  x: box.x + box.w / 2 + p.dx * box.w,
  y: box.y + box.h / 2 + p.dy * box.h,
});

/** SVG transform that places a box-sized element at the pose. */
export function poseTransform(box: Rect, p: Pose): string {
  const c = centreOf(box, p);
  return `translate(${c.x} ${c.y}) rotate(${p.rotation}) scale(${p.scale}) translate(${-box.w / 2} ${-box.h / 2})`;
}

/** The four stored corners (TL, TR, BR, BL) -- what template_positions holds. */
export function corners(box: Rect, p: Pose): { x: number; y: number }[] {
  const c = centreOf(box, p);
  const r = (p.rotation * Math.PI) / 180;
  const hw = (box.w * p.scale) / 2;
  const hh = (box.h * p.scale) / 2;
  return [
    [-hw, -hh],
    [hw, -hh],
    [hw, hh],
    [-hw, hh],
  ].map(([x, y]) => ({
    x: Math.round(c.x + x * Math.cos(r) - y * Math.sin(r)),
    y: Math.round(c.y + x * Math.sin(r) + y * Math.cos(r)),
  }));
}

export const pct = (v: number) => `${Math.round(v * 100)}%`;
export const signedPct = (v: number) => {
  const n = Math.round(v * 100);
  return n === 0 ? "0%" : `${n > 0 ? "+" : "−"}${Math.abs(n)}%`;
};
export const deg = (v: number) => {
  const n = Math.round(v);
  return n === 0 ? "0°" : `${n > 0 ? "+" : "−"}${Math.abs(n)}°`;
};
