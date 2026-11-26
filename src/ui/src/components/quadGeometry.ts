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

/** A finger's reach on a phone corner grip, in screen pixels: half the 44px
 * a touch target needs. */
export const GRIP_RADIUS_PX = 22;

/** The phone grip's radius in image units, so it covers `GRIP_RADIUS_PX` on
 * screen whatever the photo's size and however far it is scaled down.
 *
 * `shownWidth` is the overlay's width on screen and `imageWidth` the photo's
 * true width (the viewBox's). Before the overlay has a width there is no
 * scale to convert by, so it falls back to the drawn dot's own radius. */
export function gripRadius(shownWidth: number, imageWidth: number, dotRadius: number): number {
  if (shownWidth <= 0 || imageWidth <= 0) return dotRadius;
  return Math.max(dotRadius, (GRIP_RADIUS_PX * imageWidth) / shownWidth);
}

/** Where a phone grip of radius `r` sits for the corner at `p`: on the corner,
 * pulled just far enough inside the photo to be whole.
 *
 * The overlay clips at the photo's edge (and the cards round it clip too), so
 * a grip centred on a corner at the edge was half a target. Pulled in, it
 * still covers the corner's dot and every point of it is on the photo. */
export function gripCentre(p: Point, r: number, space: [number, number]): Point {
  const clamp = (v: number, size: number) =>
    size > 2 * r ? Math.min(Math.max(v, r), size - r) : size / 2;
  return { x: clamp(p.x, space[0]), y: clamp(p.y, space[1]) };
}
