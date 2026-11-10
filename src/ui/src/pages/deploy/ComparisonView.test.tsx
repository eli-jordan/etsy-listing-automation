import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ComparisonView } from "./ComparisonView";
import { buildComparison } from "./comparison";
import { sceneSource } from "../../media";
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
    gestures: [],
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

describe("ComparisonView: an image re-rendered in place", () => {
  it("shows Etsy's image replaced beside this plan's preview of it", () => {
    const ref = "hanging-on-fence:chambray";
    const p = plan([
      stage({ stage: "render", will_run: true, reason: "design or template changed" }),
      stage({
        stage: "etsy_media",
        will_run: true,
        reason: "the media manifest changed",
        snapshot: {
          live: [{ rank: 1, ref, image_id: 1, url: "https://etsy.cdn/1.jpg" }],
          desired: [{ rank: 1, ref, file: ".cache/renders/x/hanging-on-fence/chambray.png" }],
        },
        changes: [{ kind: "media", rank: 1, before: ref, after: ref }],
      }),
    ]);
    render(
      <ComparisonView
        comparison={buildComparison(p)}
        listing={{ name: "x", scene: null }}
        renderSnapshot={{
          scenes: [
            {
              scene: "hanging-on-fence/chambray",
              template: "hanging-on-fence",
              colour: "chambray",
              state: "stale",
              preview: true,
              scene_hash: "abc",
            },
          ],
        }}
        previewsRendered={new Set()}
        collapsed={false}
        etsyListingId={1}
      />,
    );

    const [before, after] = screen.getAllByAltText(ref);
    expect(before?.parentElement).toHaveClass("dv-thumb--replaced");
    expect(after?.parentElement).toHaveClass("dv-thumb--replaced");
    expect(before).toHaveAttribute("src", "https://etsy.cdn/1.jpg");
    expect(after).toHaveAttribute(
      "src",
      "/api/listings/x/previews/hanging-on-fence/chambray?hash=abc",
    );
  });
});

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
        listing={{
          name: detail().name,
          scene: sceneSource(detail().name, detail().design_content_hash),
        }}
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
        listing={{
          name: detail().name,
          scene: sceneSource(detail().name, detail().design_content_hash),
        }}
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
        listing={{
          name: detail().name,
          scene: sceneSource(detail().name, detail().design_content_hash),
        }}
        renderSnapshot={null}
        previewsRendered={new Set()}
        collapsed
        etsyListingId={1698234512}
      />,
    );

    expect(screen.getByText("On Etsy now")).toBeInTheDocument();
    expect(screen.queryByText("After apply")).not.toBeInTheDocument();
  });

  it("draws one of the listing's own images from under that listing", () => {
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
        listing={{
          name: detail().name,
          scene: sceneSource(detail().name, detail().design_content_hash),
        }}
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

describe("ComparisonView's drifted fields", () => {
  const AFTER = "First paragraph.\n\nGuaranteed for 14 days.\n\nLast paragraph.";
  const LIVE = "First paragraph.\n\nGuaranteed for 30 days.\n\nLast paragraph.";

  function renderDrift(collapsed = false) {
    const p = plan([
      stage({
        stage: "etsy_listing",
        will_run: true,
        snapshot: {
          live: { ...ETSY_LISTING_SNAPSHOT.live, description: LIVE },
          desired: { ...ETSY_LISTING_SNAPSHOT.desired, description: AFTER },
        },
        drift: [
          { path: "description", last_applied: AFTER, live: LIVE },
          {
            path: "shipping_profile_id",
            last_applied: 19283,
            live: 20011,
            last_applied_label: "Norway standard",
            live_label: "Printify default",
          },
        ],
      }),
    ]);
    render(
      <ComparisonView
        comparison={buildComparison(p)}
        listing={{ name: "x", scene: null }}
        renderSnapshot={null}
        previewsRendered={new Set()}
        collapsed={collapsed}
        etsyListingId={1}
      />,
    );
  }

  it("marks the field and opens it to show only the characters that differ", () => {
    renderDrift();
    expect(screen.getAllByText("Changed on Etsy")).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: "Compare Description" }));

    const lens = screen.getByRole("region", { name: "Description compared with this plan" });
    expect(lens).toHaveTextContent("The wording was edited on Etsy.");
    expect(Array.from(lens.querySelectorAll(".dv-del")).map((e) => e.textContent)).toEqual(["30"]);
    expect(Array.from(lens.querySelectorAll(".dv-ins")).map((e) => e.textContent)).toEqual(["14"]);
  });

  it("folds identical paragraphs until asked, and closes again", () => {
    renderDrift();
    fireEvent.click(screen.getByRole("button", { name: "Compare Description" }));
    const lens = screen.getByRole("region", { name: "Description compared with this plan" });
    expect(lens).not.toHaveTextContent("Last paragraph.");

    const [fold] = screen.getAllByRole("button", { name: /1 identical paragraph/ });
    fireEvent.click(fold as HTMLElement);
    expect(lens).toHaveTextContent("Last paragraph.");
    expect(screen.queryByRole("button", { name: /identical paragraph/ })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Close/ }));
    expect(screen.getByRole("button", { name: "Compare Description" })).toBeInTheDocument();
  });

  it("gives a setting with no block of its own a row showing both named values", () => {
    renderDrift();
    expect(screen.getAllByText("Shipping profile")).toHaveLength(2);
    expect(screen.getByText("Printify default")).toHaveClass("dv-setting");
    expect(screen.getByText("Norway standard")).toHaveClass("dv-setting");
    expect(screen.queryByText("20011")).not.toBeInTheDocument();
  });

  it("shows no drift rows in the single-column view", () => {
    renderDrift(true);
    expect(screen.queryByText("Changed on Etsy")).not.toBeInTheDocument();
  });
});

describe("ComparisonView's rendered scenes", () => {
  it("asks for the plan's own preview of a scene by the hash the plan computed", () => {
    const sceneHash = "c".repeat(64);
    const p = plan([
      stage({
        stage: "etsy_media",
        snapshot: {
          desired: [{ rank: 1, ref: "flat-lay:black", file: "x.png" }],
          live: [],
        },
      }),
    ]);
    render(
      <ComparisonView
        comparison={buildComparison(p)}
        listing={{
          name: detail().name,
          scene: sceneSource(detail().name, detail().design_content_hash),
        }}
        renderSnapshot={{
          scenes: [
            {
              scene: "flat-lay:black",
              template: "flat-lay",
              colour: "black",
              state: "missing",
              preview: true,
              scene_hash: sceneHash,
            },
          ],
        }}
        previewsRendered={new Set()}
        collapsed={false}
        etsyListingId={1698234512}
      />,
    );

    expect(
      document.querySelector(
        `img[src="/api/listings/take-a-hike/previews/flat-lay/black?hash=${sceneHash}"]`,
      ),
    ).not.toBeNull();
  });
});

describe("ComparisonView's videos", () => {
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
        listing={{
          name: detail().name,
          scene: sceneSource(detail().name, detail().design_content_hash),
        }}
        renderSnapshot={null}
        previewsRendered={new Set()}
        collapsed={collapsed}
        etsyListingId={1698234512}
      />,
    );
  }

  function block(side: "On Etsy now" | "After apply"): HTMLElement {
    const dataSide = side === "After apply" ? "after" : "before";
    const label = Array.from(
      document.querySelectorAll(`.dv-cell[data-side="${dataSide}"] .dv-eyebrow`),
    ).find((e) => e.textContent === "Videos");
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
