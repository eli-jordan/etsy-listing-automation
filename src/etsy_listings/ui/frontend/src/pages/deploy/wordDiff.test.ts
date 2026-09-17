import { describe, expect, it } from "vitest";
import { wordDiff } from "./wordDiff";

/**
 * Formats one `FieldChange`'s before/after for reading -- it does not decide
 * *whether* something changed (A2): the caller only reaches this once a
 * `FieldChange` already says the title changed, and this only marks which
 * words moved.
 */

describe("wordDiff", () => {
  it("marks every word as unchanged when the strings are identical", () => {
    expect(wordDiff("Mushroom Club Tee", "Mushroom Club Tee")).toEqual([
      { type: "same", text: "Mushroom" },
      { type: "same", text: "Club" },
      { type: "same", text: "Tee" },
    ]);
  });

  it("marks a trailing word swap as one deletion and one insertion", () => {
    expect(wordDiff("Mushroom Club Shirt", "Mushroom Club Tee")).toEqual([
      { type: "same", text: "Mushroom" },
      { type: "same", text: "Club" },
      { type: "del", text: "Shirt" },
      { type: "ins", text: "Tee" },
    ]);
  });

  it("keeps shared words on either side of a change in the middle", () => {
    expect(wordDiff("A red fox jumps", "A quick fox jumps")).toEqual([
      { type: "same", text: "A" },
      { type: "del", text: "red" },
      { type: "ins", text: "quick" },
      { type: "same", text: "fox" },
      { type: "same", text: "jumps" },
    ]);
  });

  it("marks every word inserted when there was nothing before", () => {
    expect(wordDiff("", "Brand New Title")).toEqual([
      { type: "ins", text: "Brand" },
      { type: "ins", text: "New" },
      { type: "ins", text: "Title" },
    ]);
  });

  it("marks every word deleted when there is nothing after", () => {
    expect(wordDiff("Old Title Here", "")).toEqual([
      { type: "del", text: "Old" },
      { type: "del", text: "Title" },
      { type: "del", text: "Here" },
    ]);
  });

  it("handles the real mushroom-club-tee title change from the design mock", () => {
    const before = "Mushroom Club T-Shirt, Cottagecore Mycology Tee, Unisex Soft Cotton";
    const after = "Mushroom Club Tee, Cottagecore Mushroom Shirt, Mycology Gift, Unisex";

    const tokens = wordDiff(before, after);

    // Reconstructing each side from its own tokens is an independent check
    // that no word was silently dropped or duplicated by the alignment.
    const reconstructedBefore = tokens
      .filter((t) => t.type !== "ins")
      .map((t) => t.text)
      .join(" ");
    const reconstructedAfter = tokens
      .filter((t) => t.type !== "del")
      .map((t) => t.text)
      .join(" ");
    expect(reconstructedBefore).toBe(before);
    expect(reconstructedAfter).toBe(after);
    expect(tokens.some((t) => t.type === "same" && t.text === "Mushroom")).toBe(true);
    expect(tokens.some((t) => t.type === "same" && t.text === "Club")).toBe(true);
  });
});
