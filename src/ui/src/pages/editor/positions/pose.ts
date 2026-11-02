/**
 * A listing's template position as the editor's handles edit it: the
 * template box under a uniform scale, a tilt and a move, applied in the box's
 * own unit frame and mapped to photo pixels through the template homography
 * (ADR-0058).
 *
 * A twin of `core/render/positions.py`, not an endpoint: the stage recomputes
 * the pose on every pointer move, and a request per frame would make the
 * handles lag the pointer. `pose.test.ts` runs the Python module's cases so
 * the two cannot drift. Offsets are fractions of the unit square; positive
 * rotation is clockwise in image coordinates, about the unit centre, before
 * the offset.
 */

export interface Point {
  x: number;
  y: number;
}

/** Top-left, top-right, bottom-right, bottom-left, as `template.yaml` orders them. */
export type Quad = readonly [Point, Point, Point, Point];

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

const UNIT: readonly Point[] = [
  { x: 0, y: 0 },
  { x: 1, y: 0 },
  { x: 1, y: 1 },
  { x: 0, y: 1 },
];

type Matrix = number[]; // 3x3, row-major

function pivotRow(m: number[][], col: number): number {
  let pivot = col;
  for (let r = col + 1; r < m.length; r++) {
    if (Math.abs(m[r][col]) > Math.abs(m[pivot][col])) pivot = r;
  }
  return pivot;
}

/** Subtracts row `col` from every other row, zeroing column `col` there. */
function eliminate(m: number[][], col: number): void {
  m.forEach((row, r) => {
    if (r === col) return;
    const f = row[col] / m[col][col];
    for (let c = col; c < row.length; c++) row[c] -= f * m[col][c];
  });
}

/** Gauss-Jordan elimination with partial pivoting; `null` for a singular system. */
function solve(rows: number[][], values: number[]): number[] | null {
  const n = values.length;
  const m = rows.map((row, i) => [...row, values[i]]);
  for (let col = 0; col < n; col++) {
    const pivot = pivotRow(m, col);
    if (Math.abs(m[pivot][col]) < 1e-12) return null;
    [m[col], m[pivot]] = [m[pivot], m[col]];
    eliminate(m, col);
  }
  return m.map((row, i) => row[n] / row[i]);
}

/** The homography taking the unit square onto `box`. */
export function homography(box: Quad): Matrix {
  const rows: number[][] = [];
  const values: number[] = [];
  UNIT.forEach(({ x: u, y: v }, i) => {
    const p = box[i];
    rows.push([u, v, 1, 0, 0, 0, -u * p.x, -v * p.x], [0, 0, 0, u, v, 1, -u * p.y, -v * p.y]);
    values.push(p.x, p.y);
  });
  const h = solve(rows, values);
  if (h === null) throw new Error("template box has no invertible homography");
  return [...h, 1];
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

function mapAll(points: readonly Point[], m: Matrix): Point[] {
  const projected = points.map(({ x, y }) => [
    m[0] * x + m[1] * y + m[2],
    m[3] * x + m[4] * y + m[5],
    m[6] * x + m[7] * y + m[8],
  ]);
  const w = projected.map((p) => p[2]);
  if (!(w.every((v) => v > HORIZON) || w.every((v) => v < -HORIZON))) {
    throw new Error("position crosses the template homography's horizon");
  }
  return projected.map(([x, y, z]) => ({ x: x / z, y: y / z }));
}

/** Photo pixels to the template box's unit frame -- where a pointer is, as a pose sees it. */
export function toUnit(box: Quad, point: Point): Point {
  return mapAll([point], invert(homography(box)))[0];
}

/** Unit-frame points to photo pixels. */
export function toPhoto(box: Quad, points: readonly Point[]): Point[] {
  return mapAll(points, homography(box));
}

/** `pose` applied to unit-frame points of the template box. */
export function posed(pose: Pose, points: readonly Point[]): Point[] {
  const angle = (pose.rotation * Math.PI) / 180;
  const a = pose.scale * Math.cos(angle);
  const b = pose.scale * Math.sin(angle);
  return points.map(({ x, y }) => {
    const u = x - 0.5;
    const v = y - 0.5;
    return { x: u * a - v * b + 0.5 + pose.offsetX, y: u * b + v * a + 0.5 + pose.offsetY };
  });
}

/** The four absolute corners `template_positions` stores for `pose`. */
export function compose(box: Quad, pose: Pose): Quad {
  return toPhoto(box, posed(pose, UNIT)) as unknown as Quad;
}

/** The least-squares similarity nearest `quad`, and how far its corners miss. */
export function decompose(box: Quad, quad: Quad): PoseFit {
  const target = mapAll(quad, invert(homography(box)));
  const cx = target.reduce((s, p) => s + p.x, 0) / 4;
  const cy = target.reduce((s, p) => s + p.y, 0) / 4;
  let a = 0;
  let b = 0;
  UNIT.forEach((corner, i) => {
    const sx = corner.x - 0.5;
    const sy = corner.y - 0.5;
    const tx = target[i].x - cx;
    const ty = target[i].y - cy;
    // The four unit corners have sum of squared distances 2.
    a += (sx * tx + sy * ty) / 2;
    b += (sx * ty - sy * tx) / 2;
  });
  const pose: Pose = {
    scale: Math.hypot(a, b),
    offsetX: cx - 0.5,
    offsetY: cy - 0.5,
    rotation: (Math.atan2(b, a) * 180) / Math.PI,
  };
  const back = compose(box, pose);
  const residual = Math.max(...back.map((p, i) => Math.hypot(p.x - quad[i].x, p.y - quad[i].y)));
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
