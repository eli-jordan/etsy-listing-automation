import { describe, expect, it } from "vitest";
import { diffSegments, driftVerdict, paragraphGroups } from "./driftText";

const changed = (live: string, after: string, side: "live" | "after") =>
  diffSegments(live, after, side)
    .filter((segment) => segment.kind !== "same")
    .map((segment) => segment.text);

describe("diffSegments", () => {
  it("marks only the characters that differ inside a swapped word", () => {
    expect(changed("Don&#39;t count", "Don't count", "live")).toEqual(["&#39;"]);
    expect(changed("Don&#39;t count", "Don't count", "after")).toEqual(["'"]);
  });

  it("marks whole words when more than one changes together", () => {
    expect(changed("Funny Coder Tee", "Funny Web Developer Tee", "after")).toEqual([
      "Web ",
      "Developer ",
    ]);
  });

  it("keeps each side's text whole", () => {
    const text = (side: "live" | "after") =>
      diffSegments("a bee c", "a bat c", side)
        .map((segment) => segment.text)
        .join("")
        .trim();
    expect(text("live")).toBe("a bee c");
    expect(text("after")).toBe("a bat c");
  });
});

describe("paragraphGroups", () => {
  it("groups matching paragraphs around the changed one", () => {
    expect(paragraphGroups("a\n\nb\n\nc\n\nd", "a\n\nb\n\nX\n\nd")).toEqual([
      { type: "same", paragraphs: ["a", "b"] },
      { type: "diff", live: "c", after: "X" },
      { type: "same", paragraphs: ["d"] },
    ]);
  });

  it("keeps the rest matched when a paragraph is added", () => {
    expect(paragraphGroups("a\n\nc", "a\n\nb\n\nc")).toEqual([
      { type: "same", paragraphs: ["a"] },
      { type: "diff", live: "", after: "b" },
      { type: "same", paragraphs: ["c"] },
    ]);
  });
});

describe("driftVerdict", () => {
  it("says when only spacing differs", () => {
    expect(driftVerdict("a  b\n", "a b", "on Etsy")).toBe("Only spacing or line breaks differ.");
  });

  it("names where the wording was edited", () => {
    expect(driftVerdict("a", "b", "in Printify")).toBe("The wording was edited in Printify.");
  });

  it("says when this plan already matches", () => {
    expect(driftVerdict("a", "a", "on Etsy")).toBe("This plan already matches this text.");
  });
});
