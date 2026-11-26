/** The calibrator's box arithmetic; `QuadEditor` owns the DOM half. */
import type { CanvasPoint, PhotoPoint, PhotoPx, ScreenPoint, ScreenPx } from "../pixels";
import type { BoundingBox, PhotoSpace } from "../types";

const NUDGE_PX: PhotoPx = 1;
const NUDGE_PX_FAST: PhotoPx = 8;

export const MIN_SCALE = 0.05;

function translated(box: BoundingBox, dx: PhotoPx, dy: PhotoPx): BoundingBox {
  return box.map((p) => ({ x: p.x + dx, y: p.y + dy })) as BoundingBox;
}

function centre(box: BoundingBox): PhotoPoint {
  return {
    x: box.reduce((sum, p) => sum + p.x, 0) / box.length,
    y: box.reduce((sum, p) => sum + p.y, 0) / box.length,
  };
}

export function moved(
  boxAtPress: BoundingBox,
  pointerAtPress: PhotoPoint,
  pointer: PhotoPoint,
): BoundingBox {
  return translated(boxAtPress, pointer.x - pointerAtPress.x, pointer.y - pointerAtPress.y);
}

export function nudged(box: BoundingBox, key: string, fast: boolean): BoundingBox | null {
  const step = fast ? NUDGE_PX_FAST : NUDGE_PX;
  if (key === "ArrowLeft") return translated(box, -step, 0);
  if (key === "ArrowRight") return translated(box, step, 0);
  if (key === "ArrowUp") return translated(box, 0, -step);
  if (key === "ArrowDown") return translated(box, 0, step);
  return null;
}

/** Scales by the pointer's projection on the anchor-to-corner vector, so the
 * box keeps all four angles, and with them any perspective skew. */
export function scaledAbout(
  start: BoundingBox,
  pointIndex: number,
  anchor: PhotoPoint,
  pointer: PhotoPoint,
): BoundingBox {
  const corner = start[pointIndex];
  if (!corner) return start;
  const vx = corner.x - anchor.x;
  const vy = corner.y - anchor.y;
  const lengthSquared = vx * vx + vy * vy;
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

export function cornerDragged(
  boxAtPress: BoundingBox,
  pointIndex: number,
  pointer: PhotoPoint,
  modifiers: { shift?: boolean; alt?: boolean },
): BoundingBox {
  const opposite = boxAtPress[(pointIndex + 2) % boxAtPress.length];
  if (modifiers.shift && opposite) return scaledAbout(boxAtPress, pointIndex, opposite, pointer);
  if (modifiers.alt) return scaledAbout(boxAtPress, pointIndex, centre(boxAtPress), pointer);
  return boxAtPress.map((p, i) => (i === pointIndex ? pointer : p)) as BoundingBox;
}

export function labelAnchor(box: BoundingBox): PhotoPoint {
  const xs = box.map((p) => p.x);
  const ys = box.map((p) => p.y);
  return { x: (Math.min(...xs) + Math.max(...xs)) / 2, y: Math.max(...ys) };
}

export function menuPlacement(
  clickInCanvas: CanvasPoint,
  canvasOnScreen: ScreenPoint,
  menuSize: { width: ScreenPx; height: ScreenPx },
  clipOnScreen: { right: ScreenPx; bottom: ScreenPx },
): CanvasPoint {
  const at = clickInCanvas;
  const overflowsRight = canvasOnScreen.x + at.x + menuSize.width > clipOnScreen.right;
  const overflowsBottom = canvasOnScreen.y + at.y + menuSize.height > clipOnScreen.bottom;
  return {
    x: overflowsRight ? Math.max(0, at.x - menuSize.width) : at.x,
    y: overflowsBottom ? Math.max(0, at.y - menuSize.height) : at.y,
  };
}

const MIN_TOUCH_TARGET_PX: ScreenPx = 44;
export const GRIP_RADIUS_PX = MIN_TOUCH_TARGET_PX / 2;

/** The phone grip's radius, so it covers `GRIP_RADIUS_PX` on screen. */
export function gripRadius(
  overlayScreenWidth: ScreenPx,
  viewBoxWidth: PhotoPx,
  dotRadius: PhotoPx,
): PhotoPx {
  if (overlayScreenWidth <= 0 || viewBoxWidth <= 0) return dotRadius;
  return Math.max(dotRadius, (GRIP_RADIUS_PX * viewBoxWidth) / overlayScreenWidth);
}

/** The overlay clips at the photo's edge, so a grip is pulled inside it to stay whole. */
export function gripCentre(p: PhotoPoint, r: PhotoPx, space: PhotoSpace): PhotoPoint {
  const clamp = (v: number, size: number) =>
    size > 2 * r ? Math.min(Math.max(v, r), size - r) : size / 2;
  return { x: clamp(p.x, space[0]), y: clamp(p.y, space[1]) };
}
