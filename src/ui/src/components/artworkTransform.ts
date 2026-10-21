import type { BoundingBox } from "../types";

/** Unit-square to photo-space homography. CSS matrix3d keeps the artwork
 * attached to the four photo coordinates at every responsive canvas size. */
export function artworkTransform([p0, p1, p2, p3]: BoundingBox): string {
  const dx1 = p1.x - p2.x,
    dx2 = p3.x - p2.x,
    dx3 = p0.x - p1.x + p2.x - p3.x;
  const dy1 = p1.y - p2.y,
    dy2 = p3.y - p2.y,
    dy3 = p0.y - p1.y + p2.y - p3.y;
  let g = 0,
    h = 0;
  if (dx3 !== 0 || dy3 !== 0) {
    const denominator = dx1 * dy2 - dx2 * dy1;
    if (Math.abs(denominator) < 1e-10) return "scale(0)";
    g = (dx3 * dy2 - dx2 * dy3) / denominator;
    h = (dx1 * dy3 - dx3 * dy1) / denominator;
  }
  const a = p1.x - p0.x + g * p1.x,
    b = p3.x - p0.x + h * p3.x;
  const d = p1.y - p0.y + g * p1.y,
    e = p3.y - p0.y + h * p3.y;
  return `matrix3d(${a},${d},0,${g},${b},${e},0,${h},0,0,1,0,${p0.x},${p0.y},0,1)`;
}
