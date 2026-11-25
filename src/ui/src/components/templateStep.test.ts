import { describe, expect, it } from "vitest";
import { stepPosition } from "./templateStep";

const names = ["a", "b", "c"];

describe("stepPosition", () => {
  it("counts from one", () => {
    expect(stepPosition(names, "a")).toBe("1 of 3");
    expect(stepPosition(names, "c")).toBe("3 of 3");
  });

  it("says nothing for a template outside the list", () => {
    expect(stepPosition(names, "z")).toBeNull();
    expect(stepPosition(names, null)).toBeNull();
  });
});
