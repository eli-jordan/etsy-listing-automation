import { describe, expect, it } from "vitest";
import { grownHeight, isExpandedHeight } from "./drawerSheet";

const bounds = { minimum: 250, collapsed: 620, expanded: 780 };

describe("grownHeight", () => {
  it("grows the sheet with the finger, up to its expanded height", () => {
    expect(grownHeight(100, 620, bounds)).toBe(720);
    expect(grownHeight(400, 620, bounds)).toBe(780);
  });

  it("rests where it started at no offset", () => {
    expect(grownHeight(0, 620, bounds)).toBe(620);
  });
});

describe("isExpandedHeight", () => {
  it("splits collapsed and expanded at their midpoint", () => {
    expect(isExpandedHeight(701, bounds)).toBe(true);
    expect(isExpandedHeight(700, bounds)).toBe(false);
  });
});
