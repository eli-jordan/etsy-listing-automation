import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { metaFor } from "./saveMeta";
import { timeAgo } from "./timeAgo";

describe("metaFor", () => {
  it("points an unnamed listing at the name field", () => {
    expect(metaFor({ kind: "unnamed" }, null)).toMatch(/double-click the name/i);
  });

  it("points an unwritable document at the field that caused it", () => {
    /* Since PRD 70 this state is never about incompleteness -- naming writes
       the listing, and what is missing blocks deploying it instead. What is
       left is a document that contradicts itself, and `field_errors` has
       already marked the field, so this line only reports the consequence. */
    expect(metaFor({ kind: "unsaved" }, "my-shirt")).toBe(
      "Not saved — fix the highlighted field and it will be written",
    );
  });

  it("names the listing that took the name", () => {
    expect(metaFor({ kind: "name-taken", name: "take-a-hike" }, null)).toMatch(/take-a-hike/);
  });

  it("says a failed save is kept locally, not lost", () => {
    expect(metaFor({ kind: "save-failed" }, "take-a-hike")).toMatch(/kept locally/i);
  });

  it("says it is saving while a save is in flight", () => {
    expect(metaFor({ kind: "saving" }, "take-a-hike")).toBe("Saving…");
  });

  it("shows the path and a saved-ago caption once saved", () => {
    const now = Date.now();
    render(metaFor({ kind: "saved", savedAt: now - 2 * 60_000 }, "take-a-hike"));
    expect(screen.getByText("listings/take-a-hike/listing.yaml")).toBeInTheDocument();
    expect(screen.getByText(/Saved 2 mins ago/)).toBeInTheDocument();
  });
});

describe("timeAgo", () => {
  const now = Date.now();

  it("reads as a moment ago under a minute", () => {
    expect(timeAgo(now - 30_000, now)).toBe("a moment ago");
  });

  it("rounds to whole minutes", () => {
    expect(timeAgo(now - 2 * 60_000, now)).toBe("2 mins ago");
    expect(timeAgo(now - 60_000, now)).toBe("1 min ago");
  });

  it("switches to hours past 60 minutes", () => {
    expect(timeAgo(now - 3 * 3_600_000, now)).toBe("3 hrs ago");
    expect(timeAgo(now - 3_600_000, now)).toBe("1 hr ago");
  });

  it("switches to days past 24 hours", () => {
    expect(timeAgo(now - 2 * 86_400_000, now)).toBe("2 days ago");
  });
});
