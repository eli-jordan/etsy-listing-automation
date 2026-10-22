/**
 * The calibrator's box arithmetic, in image space and nothing else.
 *
 * `QuadEditor` owns the DOM half -- mapping a pointer through the SVG's CTM,
 * measuring the menu and its clipping ancestor, routing events -- and hands
 * the numbers here. Keeping this side free of React and of the browser's
 * geometry is what lets its rules be tested as plain tables.
 */
import type { BoundingBox, Point } from "../types";

const NUDGE_PX = 1;
const NUDGE_PX_FAST = 8;

/** How far a box may be shrunk in one gesture. Not zero: at zero the box
 * collapses to a point, and a point has no corners left to drag it back
 * out by. */
export const MIN_SCALE = 0.05;

function translated(box: BoundingBox, dx: number, dy: number): BoundingBox {
  return box.map((p) => ({ x: p.x + dx, y: p.y + dy })) as BoundingBox;
}

function centre(box: BoundingBox): Point {
  return {
    x: box.reduce((sum, p) => sum + p.x, 0) / box.length,
    y: box.reduce((sum, p) => sum + p.y, 0) / box.length,
  };
}

/** `start` slid by the pointer's travel from `origin`. Both are the gesture's
 * starting values, so every move is measured from the press, never from the
 * last move -- the corners keep their offsets and a skewed quad stays skewed. */
export function moved(start: BoundingBox, origin: Point, pointer: Point): BoundingBox {
  return translated(start, pointer.x - origin.x, pointer.y - origin.y);
}

/** The box an arrow key moves `box` to, or `null` for any other key. */
export function nudged(box: BoundingBox, key: string, fast: boolean): BoundingBox | null {
  const step = fast ? NUDGE_PX_FAST : NUDGE_PX;
  if (key === "ArrowLeft") return translated(box, -step, 0);
  if (key === "ArrowRight") return translated(box, step, 0);
  if (key === "ArrowUp") return translated(box, 0, -step);
  if (key === "ArrowDown") return translated(box, 0, step);
  return null;
}

/**
 * `start`, scaled about `anchor` so that its `pointIndex` corner sits as close
 * to `pointer` as a shape-preserving scale allows.
 *
 * The factor is the pointer's projection onto the anchor-to-corner vector, so
 * dragging along that diagonal tracks the cursor exactly and dragging across
 * it does nothing -- which is what "same shape, bigger or smaller" means. Every
 * corner is then moved by the same factor, so all four angles, and therefore
 * any perspective skew the box already had, are preserved exactly.
 */
export function scaledAbout(
  start: BoundingBox,
  pointIndex: number,
  anchor: Point,
  pointer: Point,
): BoundingBox {
  const corner = start[pointIndex];
  if (!corner) return start;
  const vx = corner.x - anchor.x;
  const vy = corner.y - anchor.y;
  const lengthSquared = vx * vx + vy * vy;
  // A corner sitting on its own anchor has no direction to scale along --
  // only reachable from a degenerate box, but dividing by it would produce
  // NaN coordinates and a box that vanishes.
  if (lengthSquared === 0) return start;
  const factor = Math.max(
    MIN_SCALE,
    ((pointer.x - anchor.x) * vx + (pointer.y - anchor.y) * vy) / lengthSquared,
  );
  return start.map((p) => ({
    x: anchor.x + (p.x - anchor.x) * factor,
    y: anchor.y + (p.y - anchor.y) * factor,
  })) as BoundingBox;
}

/** A corner handle's three gestures, chosen by modifier: plain moves that
 * corner alone, shift scales about the opposite corner, alt about the centre.
 * `start` is the box as the gesture began -- scaling is defined against the
 * *original* offsets, or each move would compound on the last. */
export function cornerDragged(
  start: BoundingBox,
  pointIndex: number,
  pointer: Point,
  modifiers: { shift?: boolean; alt?: boolean },
): BoundingBox {
  const opposite = start[(pointIndex + 2) % start.length];
  if (modifiers.shift && opposite) return scaledAbout(start, pointIndex, opposite, pointer);
  if (modifiers.alt) return scaledAbout(start, pointIndex, centre(start), pointer);
  return start.map((p, i) => (i === pointIndex ? pointer : p)) as BoundingBox;
}

/** Where a box's caption hangs: centred under its lowest edge. */
export function labelAnchor(box: BoundingBox): Point {
  const xs = box.map((p) => p.x);
  const ys = box.map((p) => p.y);
  return { x: (Math.min(...xs) + Math.max(...xs)) / 2, y: Math.max(...ys) };
}

/** Where the menu goes, in canvas px: at the click `at`, pulled back on each
 * axis that would overflow `clip` (screen px), never past the canvas origin.
 * `host` is the canvas's screen position and `size` the menu's measured size. */
export function menuPlacement(
  at: Point,
  host: Point,
  size: { width: number; height: number },
  clip: { right: number; bottom: number },
): Point {
  return {
    x: host.x + at.x + size.width > clip.right ? Math.max(0, at.x - size.width) : at.x,
    y: host.y + at.y + size.height > clip.bottom ? Math.max(0, at.y - size.height) : at.y,
  };
}
