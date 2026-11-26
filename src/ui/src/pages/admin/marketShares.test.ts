import { describe, expect, it } from "vitest";
import { normalizeShares } from "./marketShares";

describe("market percentage display", () => {
  it("gives whole shares totalling 100, the spare points to the earlier of tied metrics", () => {
    expect(normalizeShares([1, 1, 1, 1, 1, 1])).toEqual([17, 17, 17, 17, 16, 16]);
  });

  it("never takes a point from a small or zero final metric to make the total 100", () => {
    expect(normalizeShares([1, 1, 1, 1, 1, 0])).toEqual([20, 20, 20, 20, 20, 0]);
    expect(normalizeShares([19.5, 19.5, 19.5, 19.5, 19.5, 2.5])).toEqual([20, 20, 20, 19, 19, 2]);
  });
});
