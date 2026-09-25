import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ComparisonView } from "./ComparisonView";
import { buildComparison } from "./comparison";
import type { EtsyListingSnapshot, ListingDetail, PlanDTO, StagePlanDTO } from "../../types";
import { stagePlan } from "../../test/helpers";

type StageOverrides = Omit<Partial<StagePlanDTO>, "snapshot" | "changes" | "outcome"> & {
  stage: StagePlanDTO["stage"];
  will_run?: boolean;
  reason?: string | null;
  blocked?: string | null;
  snapshot?: unknown;
  changes?: Extract<StagePlanDTO["outcome"], { type: "work" }>["changes"];
};

function stage(overrides: StageOverrides): StagePlanDTO {
  const { stage: stageName, ...fields } = overrides;
  return stagePlan(stageName, fields as never) as StagePlanDTO;
}

function plan(stagePlans: StagePlanDTO[], etsyListingId: number | null = 1): PlanDTO {
  return {
    listing: "x",
    is_live: etsyListingId !== null,
    etsy_listing_id: etsyListingId,
    stage_plans: stagePlans,
  };
}

function detail(): ListingDetail {
  return {
    garment_profile: "comfort-colors-1717",
    design: { default: "designs/take-a-hike.png" },
    colors: ["black"],
    brief: "",
    prices: {},
    price_overrides: {},
    artwork: {},
    pricing_plan: null,
    etsy: {
      title: "",
      description: { lead: "", text: null, ref: null },
      tags: [],
      variation_images: null,
      renewal: null,
      section: null,
      shipping_profile: null,
    },
    media: [],
    name: "take-a-hike",
    modified_at: "2026-09-17T10:00:00Z",
    status: "dirty",
    issues: [],
    field_errors: {},
    etsy_listing_id: 1698234512,
    printify_product_id: null,
    pricing_plan_name: null,
    resolved_prices: [],
    description_composed: "",
  };
}

const ETSY_LISTING_SNAPSHOT: EtsyListingSnapshot = {
  live: {
    title: "Old Title",
    description: "Old description.",
    tags: ["a"],
    materials: ["cotton"],
    shop_section: null,
    shipping_profile: null,
  },
  desired: {
    title: "New Title",
    description: "New description.",
    tags: ["a", "b"],
    materials: ["cotton"],
    shop_section: null,
    shipping_profile: null,
  },
};

describe("ComparisonView", () => {
  it("shows a single 'Not on Etsy yet' column when the plan has no listing id", () => {
    const p = plan(
      [
        stage({
          stage: "etsy_listing",
          snapshot: { desired: ETSY_LISTING_SNAPSHOT.desired, live: null },
        }),
      ],
      null,
    );
    render(
      <ComparisonView
        comparison={buildComparison(p)}
        listing={{ name: detail().name, design: detail().design }}
        renderSnapshot={null}
        previewsRendered={new Set()}
        collapsed={false}
        etsyListingId={null}
      />,
    );

    expect(screen.getByText("Not on Etsy yet.")).toBeInTheDocument();
    expect(screen.getByText("New Title")).toBeInTheDocument();
  });

  it("shows both columns with word-level title changes when there is a listing to compare against", () => {
    const p = plan([
      stage({
        stage: "etsy_listing",
        snapshot: ETSY_LISTING_SNAPSHOT,
        changes: [{ kind: "field", path: "title", before: "Old Title", after: "New Title" }],
      }),
    ]);
    render(
      <ComparisonView
        comparison={buildComparison(p)}
        listing={{ name: detail().name, design: detail().design }}
        renderSnapshot={null}
        previewsRendered={new Set()}
        collapsed={false}
        etsyListingId={1698234512}
      />,
    );

    expect(screen.getByText("On Etsy now")).toBeInTheDocument();
    expect(screen.getByText("After apply")).toBeInTheDocument();
    expect(screen.getByText("Old Title")).toBeInTheDocument();
  });

  it("collapses to a single column once applied", () => {
    const p = plan([stage({ stage: "etsy_listing", snapshot: ETSY_LISTING_SNAPSHOT })]);
    render(
      <ComparisonView
        comparison={buildComparison(p)}
        listing={{ name: detail().name, design: detail().design }}
        renderSnapshot={null}
        previewsRendered={new Set()}
        collapsed
        etsyListingId={1698234512}
      />,
    );

    expect(screen.getByText("On Etsy now")).toBeInTheDocument();
    expect(screen.queryByText("After apply")).not.toBeInTheDocument();
  });

  it("draws one of the listing's own images from under that listing (PRD 72)", () => {
    const p = plan([
      stage({
        stage: "etsy_media",
        snapshot: {
          desired: [
            { rank: 1, ref: "./shots/back.png", file: "listings/take-a-hike/shots/back.png" },
          ],
          live: [],
        },
      }),
    ]);
    render(
      <ComparisonView
        comparison={buildComparison(p)}
        listing={{ name: detail().name, design: detail().design }}
        renderSnapshot={null}
        previewsRendered={new Set()}
        collapsed={false}
        etsyListingId={1698234512}
      />,
    );

    expect(
      document.querySelector(
        'img[src="/api/listings/take-a-hike/media-files/shots/back.png/file"]',
      ),
    ).not.toBeNull();
  });
});

describe("ComparisonView's videos (PRD 71)", () => {
  const FEATURED = "common-media/size-guide.mp4";
  const SECOND = "./how-it-fits.mp4";

  function renderVideos(collapsed = false) {
    const p = plan([
      stage({
        stage: "etsy_videos",
        group: "etsy_media",
        snapshot: {
          desired: [
            { ref: FEATURED, file: FEATURED, after_images: null },
            { ref: SECOND, file: "listings/take-a-hike/how-it-fits.mp4", after_images: 2 },
          ],
          live: [
            {
              video_id: 11,
              state: "active",
              ref: "./old.mp4",
              thumbnail_url: "https://etsy/11.jpg",
            },
            { video_id: 12, state: "inactive", ref: null, thumbnail_url: null },
          ],
        },
        changes: [{ kind: "field", path: "videos.second", before: "./old.mp4", after: SECOND }],
      }),
    ]);
    render(
      <ComparisonView
        comparison={buildComparison(p)}
        listing={{ name: detail().name, design: detail().design }}
        renderSnapshot={null}
        previewsRendered={new Set()}
        collapsed={collapsed}
        etsyListingId={1698234512}
      />,
    );
  }

  function block(side: "On Etsy now" | "After apply"): HTMLElement {
    const column = screen.getByText(side).closest(".dv-col") as HTMLElement;
    const label = Array.from(column.querySelectorAll(".dv-eyebrow")).find(
      (e) => e.textContent === "Videos",
    );
    return label?.closest(".dv-block") as HTMLElement;
  }

  it("draws the videos this run places as muted clips of the files, by slot", () => {
    renderVideos();
    const after = block("After apply");
    const clips = after.querySelectorAll("video");
    expect(Array.from(clips).map((c) => c.getAttribute("src"))).toEqual([
      "/api/common-media/size-guide.mp4/file#t=0.5",
      "/api/listings/take-a-hike/media-files/how-it-fits.mp4/file#t=0.5",
    ]);
    expect(after).toHaveTextContent("Featured · 2nd");
    expect(after).toHaveTextContent("After 2 images");
  });

  it("marks a new video New, from the engine's change", () => {
    renderVideos();
    const after = block("After apply");
    expect(after.querySelectorAll(".dv-thumb__badge--new")).toHaveLength(1);
    expect(after.querySelectorAll(".dv-thumb--new video")[0]).toHaveAttribute(
      "src",
      "/api/listings/take-a-hike/media-files/how-it-fits.mp4/file#t=0.5",
    );
  });

  it("draws Etsy's videos from Etsy's own thumbnail, and marks what the run removes", () => {
    renderVideos();
    const before = block("On Etsy now");
    expect(before.querySelector("img")).toHaveAttribute("src", "https://etsy/11.jpg");
    expect(before.querySelectorAll(".dv-thumb__badge--gone")).toHaveLength(2);
    expect(before).toHaveTextContent("Not playing on Etsy");
  });
});
