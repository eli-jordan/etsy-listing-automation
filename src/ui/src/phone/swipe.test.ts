import { describe, expect, it } from "vitest";
import { classifySwipe, lockAxis } from "./swipe";

describe("lockAxis", () => {
  it("waits until the finger has really moved", () => {
    expect(lockAxis(6, 3)).toBeNull();
  });

  it("locks to the axis the move is clearly along", () => {
    expect(lockAxis(-40, 8)).toBe("x");
    expect(lockAxis(5, 30)).toBe("y");
  });

  it("refuses a diagonal, so a slanted scroll never becomes a swipe", () => {
    expect(lockAxis(30, 28)).toBeNull();
  });
});

describe("classifySwipe", () => {
  it("reads a long horizontal drag as a swipe in its direction", () => {
    expect(classifySwipe(-90, 4, 600, "x")).toBe("left");
    expect(classifySwipe(90, -4, 600, "x")).toBe("right");
  });

  it("reads a short quick flick as a swipe", () => {
    expect(classifySwipe(-35, 2, 50, "x")).toBe("left");
  });

  it("ignores a short slow drag", () => {
    expect(classifySwipe(-35, 2, 400, "x")).toBeNull();
  });

  it("ignores a move that never locked an axis", () => {
    expect(classifySwipe(-120, 110, 200, null)).toBeNull();
  });

  it("reads vertical swipes along the vertical axis", () => {
    expect(classifySwipe(3, 100, 300, "y")).toBe("down");
    expect(classifySwipe(3, -100, 300, "y")).toBe("up");
  });
});
