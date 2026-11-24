import { describe, expect, it } from "vitest";
import { adjacentTemplate, stepPosition } from "./templateStep";

const names = ["a", "b", "c"];

describe("adjacentTemplate", () => {
  it("steps forward and back through the catalog order", () => {
    expect(adjacentTemplate(names, "b", "next")).toBe("c");
    expect(adjacentTemplate(names, "b", "previous")).toBe("a");
  });

  it("stops at either end rather than wrapping", () => {
    expect(adjacentTemplate(names, "c", "next")).toBeNull();
    expect(adjacentTemplate(names, "a", "previous")).toBeNull();
  });

  it("has nowhere to go from nothing, or from a name the list lacks", () => {
    expect(adjacentTemplate(names, null, "next")).toBeNull();
    expect(adjacentTemplate(names, "z", "next")).toBeNull();
  });
});

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
