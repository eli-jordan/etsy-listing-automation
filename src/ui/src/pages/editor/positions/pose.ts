/**
 * A listing's template position as the editor's handles edit it: the
 * template box under a uniform scale, a tilt and a move, applied in the box's
 * rectified frame (its unit square scaled by its mean side lengths, so a tilt
 * is rigid) and mapped to photo pixels through the template homography
 * (ADR-0058 and its 2026-11-02 amendment).
 *
 * A twin of `core/render/positions.py`, not an endpoint: the stage recomputes
 * the pose on every pointer move, and a request per frame would make the
 * handles lag the pointer. `pose.test.ts` runs the Python module's cases so
 * the two cannot drift. Offsets are fractions of W and H; positive rotation
 * is clockwise in image coordinates, about the box centre, before the offset.
 */

export interface Point {
  x: number;
  y: number;
}

/** Top-left, top-right, bottom-right, bottom-left, as `template.yaml` orders them. */
export type Quad = [Point, Point, Point, Point];

export interface Pose {
  scale: number;
  offsetX: number;
  offsetY: number;
  /** Degrees, clockwise. */
  rotation: number;
}

/** `settings.yaml`'s `template_positions` section, as the settings read serves it. */
export interface Limits {
  scale: { min: number; max: number };
  offset: number;
  rotation: number;
}

export interface PoseFit {
  pose: Pose;
  /** The largest corner error in photo pixels -- above about 1, the box is not
   * a plain move, resize or tilt of the template's (spec, *Validation* rule 1). */
  residual: number;
}

export const IDENTITY: Pose = { scale: 1, offsetX: 0, offsetY: 0, rotation: 0 };

/** `listing_validation`'s corner tolerance (rule 1) and the round-off it allows on limits. */
export const RESIDUAL_PIXELS = 1;
const ROUNDOFF = 1e-8;
const HORIZON = 1e-12;

const UNIT: Quad = [
  { x: 0, y: 0 },
  { x: 1, y: 0 },
  { x: 1, y: 1 },
  { x: 0, y: 1 },
];

/** A 3 x 3 matrix, row-major. */
export type Matrix = [number, number, number, number, number, number, number, number, number];

const quadMap = (quad: Quad, f: (point: Point, index: 0 | 1 | 2 | 3) => Point): Quad => [
  f(quad[0], 0),
  f(quad[1], 1),
  f(quad[2], 2),
  f(quad[3], 3),
];

/** The homography taking the unit square onto `box`, in closed form
 * (Heckbert's square-to-quad). Python solves the same 8 x 8 system
 * numerically; the answer is the same matrix. */
export function homography(box: Quad): Matrix {
  const [p0, p1, p2, p3] = box;
  const dx1 = p1.x - p2.x;
  const dx2 = p3.x - p2.x;
  const dx3 = p0.x - p1.x + p2.x - p3.x;
  const dy1 = p1.y - p2.y;
  const dy2 = p3.y - p2.y;
  const dy3 = p0.y - p1.y + p2.y - p3.y;
  const det = dx1 * dy2 - dx2 * dy1;
  if (Math.abs(det) < 1e-12) throw new Error("template box has no invertible homography");
  const g = (dx3 * dy2 - dx2 * dy3) / det;
  const h = (dx1 * dy3 - dx3 * dy1) / det;
  return [
    p1.x - p0.x + g * p1.x,
    p3.x - p0.x + h * p3.x,
    p0.x,
    p1.y - p0.y + g * p1.y,
    p3.y - p0.y + h * p3.y,
    p0.y,
    g,
    h,
    1,
  ];
}

function invert(m: Matrix): Matrix {
  const [a, b, c, d, e, f, g, h, i] = m;
  const A = e * i - f * h;
  const B = -(d * i - f * g);
  const C = d * h - e * g;
  const det = a * A + b * B + c * C;
  if (Math.abs(det) < 1e-18) throw new Error("template box has no invertible homography");
  return [
    A / det,
    -(b * i - c * h) / det,
    (b * f - c * e) / det,
    B / det,
    (a * i - c * g) / det,
    -(a * f - c * d) / det,
    C / det,
    -(a * h - b * g) / det,
    (a * e - b * d) / det,
  ];
}

/** One point through `m`, with its homogeneous weight. */
function project({ x, y }: Point, m: Matrix): Point & { w: number } {
  const w = m[6] * x + m[7] * y + m[8];
  return { x: (m[0] * x + m[1] * y + m[2]) / w, y: (m[3] * x + m[4] * y + m[5]) / w, w };
}

function mapPoint(point: Point, m: Matrix): Point {
  const p = project(point, m);
  if (Math.abs(p.w) <= HORIZON || !Number.isFinite(p.x) || !Number.isFinite(p.y)) {
    throw new Error("position crosses the template homography's horizon");
  }
  return { x: p.x, y: p.y };
}

/** All four corners through `m`, on one side of its horizon. */
function mapQuad(quad: Quad, m: Matrix): Quad {
  const weights = quad.map((p) => project(p, m).w);
  if (!(weights.every((w) => w > HORIZON) || weights.every((w) => w < -HORIZON))) {
    throw new Error("position crosses the template homography's horizon");
  }
  return quadMap(quad, (p) => mapPoint(p, m));
}

/** Photo pixels to the template box's unit frame -- where a pointer is, as a pose sees it. */
export function toUnit(box: Quad, point: Point): Point {
  return mapPoint(point, invert(homography(box)));
}

/** A unit-frame point to photo pixels. */
export function toPhoto(box: Quad, point: Point): Point {
  return mapPoint(point, homography(box));
}

/** `pose` applied to the unit square's corners. */
/** `(W, H)`: the box's mean top/bottom and left/right side lengths in photo
 * pixels. Scaling the unit square by them gives the *rectified* frame, where
 * a box keeps its real proportions and a tilt is a rigid rotation (ADR-0058
 * amendment, 2026-11-02). */
export function proportions(box: Quad): { w: number; h: number } {
  const [tl, tr, br, bl] = box;
  const length = (p: Point, q: Point) => Math.hypot(q.x - p.x, q.y - p.y);
  const w = (length(tl, tr) + length(bl, br)) / 2;
  const h = (length(tl, bl) + length(tr, br)) / 2;
  if (!Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) {
    throw new Error("template box has no invertible homography");
  }
  return { w, h };
}

/** `pose` applied to the unit square's corners, through the rectified frame. */
function posed(pose: Pose, size: { w: number; h: number }): Quad {
  const angle = (pose.rotation * Math.PI) / 180;
  const a = pose.scale * Math.cos(angle);
  const b = pose.scale * Math.sin(angle);
  return quadMap(UNIT, ({ x, y }) => {
    const u = (x - 0.5) * size.w;
    const v = (y - 0.5) * size.h;
    return {
      x: (u * a - v * b) / size.w + 0.5 + pose.offsetX,
      y: (u * b + v * a) / size.h + 0.5 + pose.offsetY,
    };
  });
}

/** The four absolute corners `template_positions` stores for `pose`. */
export function compose(box: Quad, pose: Pose): Quad {
  return mapQuad(posed(pose, proportions(box)), homography(box));
}

/** The least-squares similarity nearest `quad`, fitted in the rectified frame,
 * and how far its corners miss in photo pixels. */
export function decompose(box: Quad, quad: Quad): PoseFit {
  const { w, h } = proportions(box);
  const target = mapQuad(quad, invert(homography(box)));
  const cx = target.reduce((s, p) => s + (p.x - 0.5) * w, 0) / 4;
  const cy = target.reduce((s, p) => s + (p.y - 0.5) * h, 0) / 4;
  // The four centred corners have sum of squared distances W² + H².
  const norm = w * w + h * h;
  let a = 0;
  let b = 0;
  quadMap(target, (point, index) => {
    const sx = (UNIT[index].x - 0.5) * w;
    const sy = (UNIT[index].y - 0.5) * h;
    const tx = (point.x - 0.5) * w - cx;
    const ty = (point.y - 0.5) * h - cy;
    a += (sx * tx + sy * ty) / norm;
    b += (sx * ty - sy * tx) / norm;
    return point;
  });
  const pose: Pose = {
    scale: Math.hypot(a, b),
    offsetX: cx / w,
    offsetY: cy / h,
    rotation: (Math.atan2(b, a) * 180) / Math.PI,
  };
  const back = compose(box, pose);
  const corners = [0, 1, 2, 3] as const;
  const residual = Math.max(
    ...corners.map((i) => Math.hypot(back[i].x - quad[i].x, back[i].y - quad[i].y)),
  );
  return { pose, residual };
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

export function clampPose(pose: Pose, limits: Limits): Pose {
  return {
    scale: clamp(pose.scale, limits.scale.min, limits.scale.max),
    offsetX: clamp(pose.offsetX, -limits.offset, limits.offset),
    offsetY: clamp(pose.offsetY, -limits.offset, limits.offset),
    rotation: clamp(pose.rotation, -limits.rotation, limits.rotation),
  };
}

/** Fit, then clamp: *Fit within limits* (interactions, *Position outside the limits*). */
export function nearestAllowedPose(box: Quad, quad: Quad, limits: Limits): Pose {
  return clampPose(decompose(box, quad).pose, limits);
}

/** Whether `plan` would accept the pose's components -- rule 2, with its round-off. */
export function withinLimits(pose: Pose, limits: Limits): boolean {
  return (
    pose.scale >= limits.scale.min - ROUNDOFF &&
    pose.scale <= limits.scale.max + ROUNDOFF &&
    Math.abs(pose.offsetX) <= limits.offset + ROUNDOFF &&
    Math.abs(pose.offsetY) <= limits.offset + ROUNDOFF &&
    Math.abs(pose.rotation) <= limits.rotation + ROUNDOFF
  );
}

/** The template's own box: written as no entry (interactions, *Saving*). */
export function isIdentity(pose: Pose): boolean {
  return (
    Math.abs(pose.scale - 1) < 1e-9 &&
    Math.abs(pose.offsetX) < 1e-9 &&
    Math.abs(pose.offsetY) < 1e-9 &&
    Math.abs(pose.rotation) < 1e-9
  );
}
