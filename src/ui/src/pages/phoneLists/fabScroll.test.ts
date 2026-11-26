import { describe, expect, it } from "vitest";
import { FAB_SCROLL_SLOP, fabAfterScroll } from "./fabScroll";

function run(offsets: number[]) {
  let state = { hidden: false, measuredFrom: 0 };
  return offsets.map((y) => {
    state = fabAfterScroll(state, y);
    return state.hidden;
  });
}

describe("fabAfterScroll", () => {
  it("hides once the list has scrolled down past the slop", () => {
    expect(run([4, 20, 60])).toEqual([false, true, true]);
  });

  it("comes back on the way up, measured from where the scroll turned", () => {
    expect(run([20, 400, 395, 400 - FAB_SCROLL_SLOP - 1])).toEqual([true, true, true, false]);
  });

  it("ignores a finger's jitter either way", () => {
    expect(run([200, 196, 203])).toEqual([true, true, true]);
    expect(run([200, 100, 104])).toEqual([true, false, false]);
  });

  it("always shows near the top", () => {
    expect(run([300, 300 + FAB_SCROLL_SLOP + 1, FAB_SCROLL_SLOP])).toEqual([true, true, false]);
  });
});
