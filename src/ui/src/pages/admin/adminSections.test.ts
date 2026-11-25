import { describe, expect, it } from "vitest";
import { adjacentSection } from "./adminSections";

describe("adjacentSection", () => {
  it("moves to the next section on a swipe left and back on a swipe right", () => {
    expect(adjacentSection("defaults", "left")).toBe("ai");
    expect(adjacentSection("defaults", "right")).toBe("connected");
  });

  it("goes nowhere past either end", () => {
    expect(adjacentSection("connected", "right")).toBeNull();
    expect(adjacentSection("backup", "left")).toBeNull();
  });
});
