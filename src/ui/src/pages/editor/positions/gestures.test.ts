import { describe, expect, it } from "vitest";
import { moved, nudged, resized, tilted } from "./gestures";
import { IDENTITY, type Limits, type Pose, type Quad } from "./pose";

// 100 x 200 photo pixels, so unit-frame fractions are easy to read off.
const FLAT = [
  { x: 10, y: 20 },
  { x: 110, y: 20 },
  { x: 110, y: 220 },
  { x: 10, y: 220 },
] as unknown as Quad;
const LIMITS: Limits = { scale: { min: 0.8, max: 1.1 }, offset: 0.1, rotation: 15 };

function expectPose(actual: Pose | null, expected: Partial<Pose>) {
  if (actual === null) throw new Error("expected a pose");
  for (const [key, value] of Object.entries({ ...IDENTITY, ...expected })) {
    expect(actual[key as keyof Pose]).toBeCloseTo(value, 9);
  }
}

describe("handle gestures on the stage", () => {
  it("moves by the pointer's travel, as fractions of the box", () => {
    const pose = moved(FLAT, IDENTITY, { x: 60, y: 120 }, { x: 65, y: 110 }, LIMITS);
    expectPose(pose, { offsetX: 0.05, offsetY: -0.05 });
  });

  it("stops a move at the offset limit", () => {
    const pose = moved(FLAT, IDENTITY, { x: 60, y: 120 }, { x: 90, y: 200 }, LIMITS);
    expectPose(pose, { offsetX: 0.1, offsetY: 0.1 });
  });

  it("resizes uniformly about the box centre from a corner", () => {
    // Unit (1.025, 1.025) is 1.05 times the corner's distance from the centre.
    expectPose(resized(FLAT, IDENTITY, { x: 112.5, y: 225 }, LIMITS), { scale: 1.05 });
  });

  it("stops a resize at the scale limits", () => {
    expectPose(resized(FLAT, IDENTITY, { x: 200, y: 400 }, LIMITS), { scale: 1.1 });
    expectPose(resized(FLAT, IDENTITY, { x: 60, y: 120 }, LIMITS), { scale: 0.8 });
  });

  it("keeps the offset while resizing about the moved centre", () => {
    const from = { ...IDENTITY, offsetX: 0.1 };
    expectPose(resized(FLAT, from, { x: 122.5, y: 225 }, LIMITS), { offsetX: 0.1, scale: 1.05 });
  });

  it("tilts towards the pointer in whole degrees", () => {
    // Unit (0.6, 0): atan2(-0.5, 0.1) + 90 = 11.31 degrees, clockwise.
    expectPose(tilted(FLAT, IDENTITY, { x: 70, y: 20 }, LIMITS), { rotation: 11 });
    expectPose(tilted(FLAT, IDENTITY, { x: 50, y: 20 }, LIMITS), { rotation: -11 });
  });

  it("stops a tilt at the rotation limit", () => {
    expectPose(tilted(FLAT, IDENTITY, { x: 200, y: 120 }, LIMITS), { rotation: 15 });
  });

  it.each([
    ["ArrowRight", false, { offsetX: 0.01 }],
    ["ArrowLeft", false, { offsetX: -0.01 }],
    ["ArrowDown", false, { offsetY: 0.01 }],
    ["ArrowUp", true, { offsetY: -0.05 }],
  ])("nudges with %s (shift %s)", (key, shift, expected) => {
    expectPose(nudged(IDENTITY, key, shift, LIMITS), expected);
  });

  it("stops a nudge at the limit and ignores other keys", () => {
    expectPose(nudged({ ...IDENTITY, offsetX: 0.08 }, "ArrowRight", true, LIMITS), {
      offsetX: 0.1,
    });
    expect(nudged(IDENTITY, "Enter", false, LIMITS)).toBeNull();
  });
});
