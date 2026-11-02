import { describe, expect, it } from "vitest";
import {
  type Limits,
  type Quad,
  clampPose,
  compose,
  decompose,
  IDENTITY,
  nearestAllowedPose,
} from "./pose";

/** The cases of `tests/core/unit/test_positions.py`, case for case, so this
 * twin and `core/render/positions.py` cannot drift apart (ADR-0058). */

const quad = (...points: [number, number][]): Quad =>
  points.map(([x, y]) => ({ x, y })) as unknown as Quad;

const BOX = quad([100, 200], [500, 170], [600, 800], [50, 850]);
const FLAT = quad([10, 20], [110, 20], [110, 220], [10, 220]);
const STRETCHED = quad([0, 20], [120, 20], [120, 220], [0, 220]);
const DEFAULTS: Limits = { scale: { min: 0.8, max: 1.1 }, offset: 0.1, rotation: 15 };

function expectCorners(actual: Quad, expected: Quad, digits = 7) {
  ([0, 1, 2, 3] as const).forEach((index) => {
    expect(actual[index].x).toBeCloseTo(expected[index].x, digits);
    expect(actual[index].y).toBeCloseTo(expected[index].y, digits);
  });
}

/** mulberry32: a seeded stream, for the round-trip cases. */
function seeded(seed: number) {
  let state = seed + 0x6d2b79f5;
  return (lo: number, hi: number) => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return lo + (((t ^ (t >>> 14)) >>> 0) / 4294967296) * (hi - lo);
  };
}

describe("pose maths in the template homography's frame", () => {
  it.each([
    ["perspective", BOX],
    ["flat", FLAT],
  ])("identity preserves the %s box's corners", (_, box) => {
    expectCorners(compose(box, IDENTITY), box, 8);
    const fit = decompose(box, box);
    expect(fit.pose.scale).toBeCloseTo(1, 10);
    expect(fit.residual).toBeLessThan(1e-8);
  });

  it("moves and scales in unit-frame fractions", () => {
    const actual = compose(FLAT, { scale: 0.8, offsetX: 0.1, offsetY: -0.1, rotation: 0 });
    expectCorners(actual, quad([30, 20], [110, 20], [110, 180], [30, 180]));
  });

  it.each(Array.from({ length: 25 }, (_, seed) => seed))(
    "round-trips a similarity through a perturbed perspective box (seed %i)",
    (seed) => {
      const random = seeded(seed);
      const box = BOX.map((p) => ({
        x: p.x + random(-10, 10),
        y: p.y + random(-10, 10),
      })) as unknown as Quad;
      const pose = {
        scale: random(0.5, 1.5),
        offsetX: random(-0.25, 0.25),
        offsetY: random(-0.25, 0.25),
        rotation: random(-30, 30),
      };
      const posed = compose(box, pose);
      const fitted = decompose(box, posed);
      expect(fitted.pose.scale).toBeCloseTo(pose.scale, 9);
      expect(fitted.pose.offsetX).toBeCloseTo(pose.offsetX, 9);
      expect(fitted.pose.offsetY).toBeCloseTo(pose.offsetY, 9);
      expect(fitted.pose.rotation).toBeCloseTo(pose.rotation, 7);
      expect(fitted.residual).toBeLessThan(1e-7);
      expectCorners(compose(box, fitted.pose), posed);
    },
  );

  it("measures the residual in photo pixels", () => {
    expect(decompose(FLAT, STRETCHED).residual).toBeGreaterThan(1);
  });

  it("repairs a non-uniform stretch by fitting first", () => {
    // Unit-frame x scale 1.2 and y scale 1 average to uniform scale 1.1.
    const repaired = compose(FLAT, nearestAllowedPose(FLAT, STRETCHED, DEFAULTS));
    expectCorners(repaired, quad([5, 10], [115, 10], [115, 230], [5, 230]));
  });

  it("refuses a singular template box as a geometry error", () => {
    const singular = quad([0, 0], [100, 100], [200, 200], [300, 300]);
    expect(() => decompose(singular, FLAT)).toThrow(/homography/);
  });

  it.each([
    ["perspective", BOX],
    ["flat", FLAT],
  ])("nearest allowed pose fits then clamps every component (%s)", (_, box) => {
    const outside = compose(box, { scale: 1.4, offsetX: 0.2, offsetY: -0.3, rotation: 25 });
    const nearest = nearestAllowedPose(box, outside, DEFAULTS);
    expect(nearest.scale).toBeCloseTo(1.1, 12);
    expect(nearest.offsetX).toBeCloseTo(0.1, 12);
    expect(nearest.offsetY).toBeCloseTo(-0.1, 12);
    expect(nearest.rotation).toBeCloseTo(15, 12);
    expect(decompose(box, compose(box, nearest)).residual).toBeLessThan(1e-7);
  });

  it.each([
    { scale: 0.8, offsetX: -0.1, offsetY: 0, rotation: -15 },
    { scale: 1.1, offsetX: 0, offsetY: 0.1, rotation: 15 },
  ])("leaves a pose on the allowed boundary unchanged (%o)", (pose) => {
    const box = compose(BOX, pose);
    expectCorners(compose(BOX, nearestAllowedPose(BOX, box, DEFAULTS)), box);
  });

  it("clamps each component on its own", () => {
    expect(
      clampPose({ scale: 0.5, offsetX: 0.3, offsetY: -0.05, rotation: -40 }, DEFAULTS),
    ).toEqual({ scale: 0.8, offsetX: 0.1, offsetY: -0.05, rotation: -15 });
  });
});
