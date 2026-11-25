import { describe, expect, it } from "vitest";
import { enterSide, followOffset, neighbourTab } from "./tabSwipe";

const TABS = ["variants", "pricing", "images", "details"] as const;

describe("neighbourTab", () => {
  it("moves to the next tab on a left swipe and the previous on a right", () => {
    expect(neighbourTab(TABS, "pricing", "left")).toBe("images");
    expect(neighbourTab(TABS, "pricing", "right")).toBe("variants");
  });

  it("stops at either end", () => {
    expect(neighbourTab(TABS, "variants", "right")).toBeNull();
    expect(neighbourTab(TABS, "details", "left")).toBeNull();
  });

  it("ignores vertical directions and unknown tabs", () => {
    expect(neighbourTab(TABS, "pricing", "up")).toBeNull();
    expect(neighbourTab<string>(TABS, "nope", "left")).toBeNull();
  });
});

describe("enterSide", () => {
  it("brings a later tab in from the right and an earlier one from the left", () => {
    expect(enterSide(TABS, "variants", "details")).toBe("right");
    expect(enterSide(TABS, "images", "pricing")).toBe("left");
  });
});

describe("followOffset", () => {
  it("follows the finger when there is a tab to go to", () => {
    expect(followOffset(TABS, "pricing", -50)).toBe(-50);
    expect(followOffset(TABS, "pricing", 50)).toBe(50);
  });

  it("resists past the first and the last tab", () => {
    expect(Math.abs(followOffset(TABS, "variants", 100))).toBeLessThan(100);
    expect(Math.abs(followOffset(TABS, "details", -100))).toBeLessThan(100);
  });
});
