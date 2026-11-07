import { describe, expect, it } from "vitest";
import { garmentSample } from "./liveRenderer";
import type { Quad } from "./pose";

const BOX = [
  { x: 100, y: 200 },
  { x: 300, y: 200 },
  { x: 300, y: 600 },
  { x: 100, y: 600 },
] as unknown as Quad;

describe("garmentSample", () => {
  it("measures the middle of the box, as a fraction of the photo", () => {
    const [u, v] = garmentSample(BOX, { w: 400, h: 800 });
    expect(u).toBeCloseTo(0.5);
    expect(v).toBeCloseTo(0.5);
  });

  it("averages over half the box's shorter side", () => {
    const [, , level] = garmentSample(BOX, { w: 400, h: 800 });
    expect(2 ** level).toBeCloseTo(100);
  });
});
