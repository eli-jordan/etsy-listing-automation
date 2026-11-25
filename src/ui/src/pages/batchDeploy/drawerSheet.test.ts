import { describe, expect, it } from "vitest";
import { isExpandedHeight, sheetDrag } from "./drawerSheet";

const bounds = { minimum: 250, collapsed: 620, expanded: 780 };

describe("sheetDrag", () => {
  it("moves the whole sheet down with the finger, keeping its height", () => {
    expect(sheetDrag(120, 620, bounds)).toEqual({ translate: 120, height: 620 });
  });

  it("grows the sheet when pulled up, up to its expanded height", () => {
    expect(sheetDrag(-100, 620, bounds)).toEqual({ translate: 0, height: 720 });
    expect(sheetDrag(-400, 620, bounds)).toEqual({ translate: 0, height: 780 });
  });

  it("rests where it started at no offset", () => {
    expect(sheetDrag(0, 620, bounds)).toEqual({ translate: 0, height: 620 });
  });
});

describe("isExpandedHeight", () => {
  it("splits collapsed and expanded at their midpoint", () => {
    expect(isExpandedHeight(701, bounds)).toBe(true);
    expect(isExpandedHeight(700, bounds)).toBe(false);
  });
});
