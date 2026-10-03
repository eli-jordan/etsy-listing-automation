import { describe, expect, it } from "vitest";
import type { BoundingBox } from "../types";
import {
  cornerDragged,
  labelAnchor,
  menuPlacement,
  MIN_SCALE,
  moved,
  nudged,
  scaledAbout,
} from "./quadGeometry";

/** Corners at (0,0), (100,0), (100,100), (0,100): a factor `f` about the
 * origin lands on numbers you can read straight off an assertion. */
const SQUARE: BoundingBox = [
  { x: 0, y: 0 },
  { x: 100, y: 0 },
  { x: 100, y: 100 },
  { x: 0, y: 100 },
];

/** Already skewed, off the origin: a scale that kept the shape of a square
 * but not of this would be caught here. */
const SKEWED: BoundingBox = [
  { x: 10, y: 20 },
  { x: 110, y: 30 },
  { x: 120, y: 140 },
  { x: 0, y: 120 },
];

const scaleBy = (box: BoundingBox, f: number, a: { x: number; y: number }) =>
  box.map((p) => ({ x: a.x + (p.x - a.x) * f, y: a.y + (p.y - a.y) * f }));

describe("moved", () => {
  it("translates every corner by the pointer's travel from the gesture origin", () => {
    expect(moved(SKEWED, { x: 5, y: 5 }, { x: 35, y: -5 })).toEqual([
      { x: 40, y: 10 },
      { x: 140, y: 20 },
      { x: 150, y: 130 },
      { x: 30, y: 110 },
    ]);
  });

  it("is anchored at the gesture start, so the same pointer gives the same box", () => {
    const once = moved(SQUARE, { x: 0, y: 0 }, { x: 7, y: 3 });
    expect(moved(SQUARE, { x: 0, y: 0 }, { x: 7, y: 3 })).toEqual(once);
    expect(once).not.toEqual(SQUARE);
  });
});

describe("nudged", () => {
  it.each([
    ["ArrowLeft", false, -1, 0],
    ["ArrowRight", false, 1, 0],
    ["ArrowUp", false, 0, -1],
    ["ArrowDown", false, 0, 1],
    ["ArrowLeft", true, -8, 0],
    ["ArrowRight", true, 8, 0],
    ["ArrowUp", true, 0, -8],
    ["ArrowDown", true, 0, 8],
  ])("%s (shift %s) moves every corner by (%i, %i)", (key, fast, dx, dy) => {
    expect(nudged(SKEWED, key, fast)).toEqual(SKEWED.map((p) => ({ x: p.x + dx, y: p.y + dy })));
  });

  it.each(["a", "Enter", "Delete", "Home"])("%s is not a nudge", (key) => {
    expect(nudged(SKEWED, key, false)).toBeNull();
  });
});

describe("cornerDragged", () => {
  // Bottom-right is corner 2; its opposite is corner 0 and the centre (50,50).
  it("plain drag moves that corner alone, whatever its distance", () => {
    expect(cornerDragged(SQUARE, 2, { x: 160, y: 40 }, {})).toEqual([
      { x: 0, y: 0 },
      { x: 100, y: 0 },
      { x: 160, y: 40 },
      { x: 0, y: 100 },
    ]);
  });

  it.each([
    [{ shift: true }, { x: 200, y: 200 }, 2, { x: 0, y: 0 }],
    [{ shift: true }, { x: 50, y: 50 }, 0.5, { x: 0, y: 0 }],
    [{ alt: true }, { x: 150, y: 150 }, 2, { x: 50, y: 50 }],
    [{ alt: true }, { x: 75, y: 75 }, 0.5, { x: 50, y: 50 }],
    // Shift wins when both are held.
    [{ shift: true, alt: true }, { x: 200, y: 200 }, 2, { x: 0, y: 0 }],
  ])("%o to %o scales by %f about %o", (modifiers, pointer, factor, anchor) => {
    expect(cornerDragged(SQUARE, 2, pointer, modifiers)).toEqual(scaleBy(SQUARE, factor, anchor));
  });

  it("shift on a skewed box keeps every corner proportional to the opposite one", () => {
    // Corner 2 is (110,120) from corner 0; projecting double that gives 2.
    const pointer = { x: 10 + 220, y: 20 + 240 };
    const got = cornerDragged(SKEWED, 2, pointer, { shift: true });
    scaleBy(SKEWED, 2, { x: 10, y: 20 }).forEach((p, i) => {
      expect(got[i]?.x).toBeCloseTo(p.x);
      expect(got[i]?.y).toBeCloseTo(p.y);
    });
  });
});

describe("scaledAbout", () => {
  const origin = { x: 0, y: 0 };

  it("counts only the projection on the diagonal, so a sideways pointer keeps the shape", () => {
    expect(scaledAbout(SQUARE, 2, origin, { x: 100, y: 0 })).toEqual(scaleBy(SQUARE, 0.5, origin));
  });

  it("will not shrink past MIN_SCALE, even dragged through the anchor", () => {
    expect(scaledAbout(SQUARE, 2, origin, { x: -400, y: -400 })).toEqual(
      scaleBy(SQUARE, MIN_SCALE, origin),
    );
  });

  it("leaves a corner sitting on its own anchor alone rather than dividing by zero", () => {
    expect(scaledAbout(SQUARE, 0, origin, { x: 50, y: 50 })).toBe(SQUARE);
  });

  it("leaves the box alone for a corner that does not exist", () => {
    expect(scaledAbout(SQUARE, 7, origin, { x: 50, y: 50 })).toBe(SQUARE);
  });
});

describe("labelAnchor", () => {
  it("hangs under the lowest edge, centred on the horizontal extent", () => {
    expect(labelAnchor(SKEWED)).toEqual({ x: 60, y: 140 });
  });
});

describe("menuPlacement", () => {
  const size = { width: 150, height: 90 };
  // Canvas at (100, 50) on screen; the clip box ends at (500, 250).
  const host = { x: 100, y: 50 };
  const clip = { right: 500, bottom: 250 };

  it.each([
    ["room on both axes", { x: 20, y: 20 }, clip, { x: 20, y: 20 }],
    ["pulled back horizontally only", { x: 380, y: 20 }, clip, { x: 230, y: 20 }],
    ["pulled back vertically only", { x: 20, y: 160 }, clip, { x: 20, y: 70 }],
    ["pulled back on both", { x: 380, y: 190 }, clip, { x: 230, y: 100 }],
    ["exactly touching the edge stays", { x: 250, y: 110 }, clip, { x: 250, y: 110 }],
    [
      "never pulled past the canvas origin",
      { x: 100, y: 60 },
      { right: 300, bottom: 150 },
      { x: 0, y: 0 },
    ],
  ])("%s", (_, at, clipBox, expected) => {
    expect(menuPlacement(at, host, size, clipBox)).toEqual(expected);
  });
});
