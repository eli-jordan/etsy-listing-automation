import { describe, expect, it } from "vitest";
import { gripRadius, menuPlacement } from "./components/quadGeometry";
import type { PhotoPoint, PhotoPx } from "./pixels";

// The @ts-expect-error lines are the assertions: `npm run typecheck` fails if a
// brand stops refusing another space.
describe("pixel spaces", () => {
  it("refuses a photo length where a screen length is expected", () => {
    const photoWidth: PhotoPx = 4000;
    // @ts-expect-error the overlay's width is measured on screen
    expect(gripRadius(photoWidth, photoWidth, 10)).toBe(22);
  });

  it("refuses a photo point where a canvas point is expected", () => {
    const corner: PhotoPoint = { x: 10, y: 20 };
    const menu = { width: 5, height: 5 };
    const clip = { right: 100, bottom: 100 };
    // @ts-expect-error the click is measured from the canvas's corner
    expect(menuPlacement(corner, { x: 0, y: 0 }, menu, clip)).toEqual({ x: 10, y: 20 });
  });

  it("takes a plain number in any space", () => {
    expect(gripRadius(400, 4000, 10)).toBe(220);
  });
});
