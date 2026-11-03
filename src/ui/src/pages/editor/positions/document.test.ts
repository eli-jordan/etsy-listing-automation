import { describe, expect, it } from "vitest";
import type { Issue } from "../../../types";
import {
  type Positions,
  positionSignature,
  removablePosition,
  storedBox,
  withPose,
  withoutPosition,
} from "./document";
import { type Limits, IDENTITY, type Quad, decompose, withinLimits } from "./pose";

const BOX = [
  { x: 100, y: 200 },
  { x: 500, y: 170 },
  { x: 600, y: 800 },
  { x: 50, y: 850 },
] as unknown as Quad;
const MOVED = [
  { x: 10, y: 20 },
  { x: 110, y: 20 },
  { x: 110, y: 220 },
  { x: 10, y: 220 },
] as unknown as Quad;
const LIMITS: Limits = { scale: { min: 0.8, max: 1.1 }, offset: 0.1, rotation: 15 };
const corners = (box: Quad) => [...box];

describe("template_positions as the editor writes it", () => {
  it("reads a single box and a placement's box", () => {
    const positions: Positions = {
      folded: { bounding_box: MOVED },
      pair: { placements: { left: { bounding_box: BOX } } },
    };
    expect(storedBox(positions, "folded", null)).toEqual(MOVED);
    expect(storedBox(positions, "pair", "left")).toEqual(BOX);
    expect(storedBox(positions, "pair", "right")).toBeNull();
    expect(storedBox(positions, "other", null)).toBeNull();
    expect(storedBox(null, "folded", null)).toBeNull();
  });

  it("writes a posed box beside the other templates' entries", () => {
    const pose = { ...IDENTITY, scale: 0.9 };
    const next = withPose({ other: { bounding_box: MOVED } }, "folded", null, BOX, pose, LIMITS);
    expect(next?.other).toEqual({ bounding_box: MOVED });
    const box = storedBox(next, "folded", null);
    expect(box).not.toBeNull();
    expect(decompose(BOX, box as Quad).pose.scale).toBeCloseTo(0.9, 6);
  });

  it("writes a placement's box beside its sibling placements", () => {
    const positions: Positions = { pair: { placements: { left: { bounding_box: MOVED } } } };
    const next = withPose(positions, "pair", "right", BOX, { ...IDENTITY, rotation: 5 }, LIMITS);
    expect(storedBox(next, "pair", "left")).toEqual(MOVED);
    expect(storedBox(next, "pair", "right")).not.toBeNull();
  });

  it("keeps a pose on the limit inside the limit once stored", () => {
    const pose = { scale: 1.1, offsetX: -0.1, offsetY: 0.1, rotation: 15 };
    const box = storedBox(withPose(null, "folded", null, BOX, pose, LIMITS), "folded", null);
    expect(withinLimits(decompose(BOX, box as Quad).pose, LIMITS)).toBe(true);
  });

  it("writes the template's own box as no entry", () => {
    expect(
      withPose({ folded: { bounding_box: MOVED } }, "folded", null, BOX, IDENTITY, LIMITS),
    ).toBeNull();
  });

  it("removes one placement, then the template once none is left", () => {
    const positions: Positions = {
      pair: { placements: { left: { bounding_box: MOVED }, right: { bounding_box: BOX } } },
      folded: { bounding_box: MOVED },
    };
    const once = withoutPosition(positions, "pair", "left");
    expect(once).toEqual({
      pair: { placements: { right: { bounding_box: BOX } } },
      folded: { bounding_box: MOVED },
    });
    expect(withoutPosition(once, "pair", "right")).toEqual({ folded: { bounding_box: MOVED } });
    expect(withoutPosition({ folded: { bounding_box: MOVED } }, "folded", null)).toBeNull();
  });

  it("signs a template's entry so a saved change is a new preview URL", () => {
    const a = positionSignature({ bounding_box: corners(MOVED) as unknown as Quad });
    const b = positionSignature({ bounding_box: corners(BOX) as unknown as Quad });
    expect(a).not.toEqual(b);
    expect(positionSignature({ bounding_box: MOVED })).toEqual(a);
    expect(positionSignature(undefined)).toBe("");
  });
});

const issue = (where: string, message: string): Issue => ({
  severity: "block",
  tab: "images",
  where,
  message,
});

describe("which banner rows remove a key the stage cannot show", () => {
  it.each([
    [
      "template_positions.old-scene",
      "frog-tee: template_positions.old-scene names a template that is not in media",
      { template: "old-scene", placement: null },
    ],
    [
      "template_positions.family-chart.placements.left-shirt",
      "frog-tee: template_positions.family-chart.placements.left-shirt names a placement that no longer exists",
      { template: "family-chart", placement: "left-shirt" },
    ],
    [
      "template_positions.family-chart",
      "frog-tee: template_positions.family-chart uses bounding_box on a multiple template; use placements instead",
      { template: "family-chart", placement: null },
    ],
  ])("offers removal for %s", (where, message, expected) => {
    expect(removablePosition(issue(where, message))).toEqual(expected);
  });

  it.each([
    "frog-tee: template_positions.front-flatlay scales the design to 1.18; the limit is 0.80–1.10",
    "frog-tee: template_positions.front-flatlay has horizontal offset 11%; the limit is ±10%",
    "frog-tee: template_positions.front-flatlay has rotation 18°; the limit is ±15°",
    "frog-tee: template_positions.front-flatlay is not a plain move, resize or tilt of the template's box",
  ])("leaves a pose the stage can fit to the stage: %s", (message) => {
    expect(removablePosition(issue("template_positions.front-flatlay", message))).toBeNull();
  });

  it("ignores rows about anything else", () => {
    expect(removablePosition(issue("Listing Images", "Add an image"))).toBeNull();
  });
});
