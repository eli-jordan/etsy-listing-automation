import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ListingDetail } from "../../types";
import { metaFor } from "./saveMeta";
import { timeAgo } from "./timeAgo";

function detail(over: Partial<ListingDetail> = {}): ListingDetail {
  return {
    garment_profile: "comfort-colors-1717",
    design: { default: "../../designs/take-a-hike.png" },
    colors: ["black"],
    brief: "",
    prices: {},
    price_overrides: {},
    artwork: {},
    pricing_plan: null,
    etsy: {
      title: "<generate>",
      description: "<generate>",
      tags: "<generate>",
      materials: [],
      variation_images: null,
      renewal: null,
      section: null,
      shipping_profile: null,
    },
    media: [],
    name: "take-a-hike",
    status: "draft",
    issues: [],
    field_errors: {},
    etsy_listing_id: null,
    printify_product_id: null,
    pricing_plan_name: null,
    resolved_prices: [],
    ...over,
  };
}
describe("metaFor", () => {
  it("points an unnamed listing at the name field", () => {
    expect(metaFor({ kind: "unnamed" }, detail(), null)).toMatch(/double-click the name/i);
  });

  it("names the price source when it is the only thing left", () => {
    const blocked = detail({
      issues: [
        {
          severity: "block",
          tab: "details",
          where: "Listing Details › Pricing",
          message: "No pricing plan and no prices",
        },
      ],
    });
    expect(metaFor({ kind: "unsaved" }, blocked, "my-shirt")).toMatch(/pricing plan/i);
  });

  it("counts the problems when there is more than one", () => {
    const blocked = detail({
      issues: [
        { severity: "block", tab: "details", where: "Listing Details › Pricing", message: "x" },
        { severity: "block", tab: "variants", where: "Design", message: "y" },
      ],
    });
    expect(metaFor({ kind: "unsaved" }, blocked, "my-shirt")).toBe(
      "Not saved — 2 problems above have to be fixed first",
    );
  });

  it("names the listing that took the name", () => {
    expect(metaFor({ kind: "name-taken", name: "take-a-hike" }, detail(), null)).toMatch(
      /take-a-hike/,
    );
  });

  it("says it is saving while a save is in flight", () => {
    expect(metaFor({ kind: "saving" }, detail(), "take-a-hike")).toBe("Saving…");
  });

  it("shows the path and a saved-ago caption once saved", () => {
    const now = Date.now();
    render(metaFor({ kind: "saved", savedAt: now - 2 * 60_000 }, detail(), "take-a-hike"));
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
