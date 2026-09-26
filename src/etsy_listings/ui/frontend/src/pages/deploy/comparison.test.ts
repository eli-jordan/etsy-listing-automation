import { describe, expect, it } from "vitest";
import { buildComparison } from "./comparison";
import type {
  EtsyListingSnapshot,
  EtsyMediaSnapshot,
  EtsyVideosSnapshot,
  PlanDTO,
  ProductSnapshot,
  PublishSnapshot,
  StagePlanDTO,
} from "../../types";
import { stagePlan } from "../../test/helpers";

/**
 * Pure: snapshots + changes -> before/after blocks, impact tags, price rows,
 * image badges (docs/deploy-changes.md, Frontend module table; decision 3/4).
 *
 * Every fixture below is shaped exactly like the real DTOs (`ui/runs/events.py`,
 * the five stages' own `snapshot()` methods) so a passing test here is a
 * passing test against the wire format, not an invented shorthand.
 */

type StageOverrides = Omit<Partial<StagePlanDTO>, "snapshot" | "changes" | "outcome"> & {
  stage: StagePlanDTO["stage"];
  will_run?: boolean;
  reason?: string | null;
  blocked?: string | null;
  /** Test fixtures supply the snapshot belonging to the selected stage. */
  snapshot?: unknown;
  changes?: Extract<StagePlanDTO["outcome"], { type: "work" }>["changes"];
};

function stage(overrides: StageOverrides): StagePlanDTO {
  const { stage: stageName, ...fields } = overrides;
  return stagePlan(stageName, fields as never) as StagePlanDTO;
}

function plan(stagePlans: StagePlanDTO[], etsyListingId: number | null = 1698234512): PlanDTO {
  return {
    listing: "mushroom-club-tee",
    is_live: etsyListingId !== null,
    etsy_listing_id: etsyListingId,
    stage_plans: stagePlans,
  };
}

const PRODUCT_SNAPSHOT: ProductSnapshot = {
  live: [
    { size: "S", colour: "black", price: "349 NOK" },
    { size: "M", colour: "black", price: "349 NOK" },
    { size: "S", colour: "ivory", price: "349 NOK" },
  ],
  desired: [
    { size: "S", colour: "black", price: "379 NOK" },
    { size: "M", colour: "black", price: "379 NOK" },
    { size: "S", colour: "ivory", price: "379 NOK" },
    { size: "S", colour: "moss", price: "379 NOK" },
  ],
};

const ETSY_LISTING_SNAPSHOT: EtsyListingSnapshot = {
  live: {
    title: "Mushroom Club T-Shirt, Cottagecore Mycology Tee, Unisex Soft Cotton",
    description: "A cottagecore tee for the mushroom-obsessed.",
    tags: ["mushroom club", "cottagecore", "mushroom t shirt"],
    materials: ["cotton"],
    shop_section: "Mushrooms",
    shipping_profile: "Norway standard",
  },
  desired: {
    title: "Mushroom Club Tee, Cottagecore Mushroom Shirt, Mycology Gift, Unisex",
    description: "A cottagecore tee for the mushroom-obsessed mycology lover.",
    tags: ["mushroom club", "cottagecore", "mycology gift"],
    materials: ["cotton", "polyester"],
    shop_section: "Mushrooms",
    shipping_profile: "Norway standard",
  },
};

const ETSY_MEDIA_SNAPSHOT: EtsyMediaSnapshot = {
  live: [
    { rank: 1, ref: "lifestyle-02:black", image_id: 1, url: "https://etsy.cdn/1.jpg" },
    { rank: 2, ref: "flat-lay-01:ivory", image_id: 2, url: "https://etsy.cdn/2.jpg" },
    { rank: 3, ref: "closeup-01:black", image_id: 3, url: "https://etsy.cdn/3.jpg" },
  ],
  desired: [
    { rank: 1, ref: "lifestyle-02:moss", file: ".cache/renders/x/lifestyle-02--moss.png" },
    { rank: 2, ref: "lifestyle-02:black", file: ".cache/renders/x/lifestyle-02--black.png" },
    { rank: 3, ref: "flat-lay-01:ivory", file: ".cache/renders/x/flat-lay-01--ivory.png" },
  ],
};

function fullPlan(): PlanDTO {
  return plan([
    stage({ stage: "render", will_run: true, reason: "referenced scenes changed" }),
    stage({
      stage: "printify_product",
      will_run: true,
      reason: "the product differs from the listing",
      snapshot: PRODUCT_SNAPSHOT,
      changes: [
        { kind: "list", path: "colors", added: ["moss"], removed: [], reordered: false },
        { kind: "field", path: "variants", before: 18, after: 24 },
        { kind: "price", size: "S", before: "349 NOK", after: "379 NOK", color: "black" },
        { kind: "price", size: "M", before: "349 NOK", after: "379 NOK", color: "black" },
      ],
    }),
    stage({
      stage: "publish",
      will_run: true,
      reason: "the variant matrix differs from what Etsy has",
    }),
    stage({
      stage: "etsy_listing",
      will_run: true,
      reason: "the listing's copy or settings changed",
      snapshot: ETSY_LISTING_SNAPSHOT,
      changes: [
        {
          kind: "field",
          path: "title",
          before: ETSY_LISTING_SNAPSHOT.live?.title ?? null,
          after: ETSY_LISTING_SNAPSHOT.desired.title,
        },
        {
          kind: "field",
          path: "description",
          before: ETSY_LISTING_SNAPSHOT.live?.description ?? null,
          after: ETSY_LISTING_SNAPSHOT.desired.description,
        },
        {
          kind: "list",
          path: "tags",
          added: ["mycology gift"],
          removed: ["mushroom t shirt"],
          reordered: false,
        },
        {
          kind: "list",
          path: "materials",
          added: ["polyester"],
          removed: [],
          reordered: false,
        },
      ],
    }),
    stage({
      stage: "etsy_media",
      will_run: true,
      reason: "the media manifest changed",
      snapshot: ETSY_MEDIA_SNAPSHOT,
      changes: [
        { kind: "media", rank: 1, before: "lifestyle-02:black", after: "lifestyle-02:moss" },
        { kind: "media", rank: 3, before: "closeup-01:black", after: "flat-lay-01:ivory" },
      ],
    }),
  ]);
}

describe("buildComparison: impact tags", () => {
  it("names every part of the listing the plan touches, in reading order", () => {
    const comparison = buildComparison(fullPlan());

    expect(comparison.impacts).toEqual([
      "Images",
      "Title",
      "Description",
      "Prices",
      "Colours",
      "Tags",
      "Materials",
    ]);
  });

  it("is empty when nothing will run", () => {
    const clean = plan([
      stage({ stage: "render" }),
      stage({ stage: "printify_product", snapshot: { desired: [], live: [] } }),
      stage({ stage: "publish" }),
      stage({
        stage: "etsy_listing",
        snapshot: {
          desired: {
            title: "x",
            description: "",
            tags: [],
            materials: [],
            shop_section: null,
            shipping_profile: null,
          },
          live: null,
        },
      }),
      stage({ stage: "etsy_media", snapshot: { desired: [], live: [] } }),
    ]);

    expect(buildComparison(clean).impacts).toEqual([]);
  });
});

describe("buildComparison: title", () => {
  it("carries both sides and the changed flag from the FieldChange", () => {
    const { title } = buildComparison(fullPlan());

    expect(title).toEqual({
      before: ETSY_LISTING_SNAPSHOT.live?.title ?? null,
      after: ETSY_LISTING_SNAPSHOT.desired.title,
      changed: true,
    });
  });

  it("is null when the etsy_listing stage never produced a snapshot", () => {
    const blockedListing = plan([
      stage({ stage: "render" }),
      stage({ stage: "printify_product" }),
      stage({ stage: "publish", blocked: "no shop configured" }),
      stage({ stage: "etsy_listing", blocked: "no shop configured" }),
      stage({ stage: "etsy_media", blocked: "no shop configured" }),
    ]);

    expect(buildComparison(blockedListing).title).toBeNull();
  });
});

describe("buildComparison: description", () => {
  it("carries both sides and the changed flag from the FieldChange", () => {
    const { description } = buildComparison(fullPlan());

    expect(description).toEqual({
      before: ETSY_LISTING_SNAPSHOT.live?.description ?? null,
      after: ETSY_LISTING_SNAPSHOT.desired.description,
      changed: true,
    });
  });

  it("is not flagged changed by a pending edit to some other field", () => {
    const titleOnly = plan([
      stage({ stage: "render" }),
      stage({ stage: "printify_product", snapshot: { desired: [], live: [] } }),
      stage({ stage: "publish" }),
      stage({
        stage: "etsy_listing",
        snapshot: ETSY_LISTING_SNAPSHOT,
        changes: [
          {
            kind: "field",
            path: "title",
            before: ETSY_LISTING_SNAPSHOT.live?.title ?? null,
            after: ETSY_LISTING_SNAPSHOT.desired.title,
          },
        ],
      }),
      stage({ stage: "etsy_media", snapshot: { desired: [], live: [] } }),
    ]);

    expect(buildComparison(titleOnly).description?.changed).toBe(false);
  });
});

describe("buildComparison: tags", () => {
  it("carries both sides plus what was added and removed", () => {
    const { tags } = buildComparison(fullPlan());

    expect(tags).toEqual({
      before: ETSY_LISTING_SNAPSHOT.live?.tags ?? [],
      after: ETSY_LISTING_SNAPSHOT.desired.tags,
      added: ["mycology gift"],
      removed: ["mushroom t shirt"],
      changed: true,
    });
  });
});

describe("buildComparison: materials", () => {
  it("carries both sides plus what was added and removed", () => {
    const { materials } = buildComparison(fullPlan());

    expect(materials).toEqual({
      before: ETSY_LISTING_SNAPSHOT.live?.materials ?? [],
      after: ETSY_LISTING_SNAPSHOT.desired.materials,
      added: ["polyester"],
      removed: [],
      changed: true,
    });
  });
});

describe("buildComparison: colours", () => {
  it("names the colours on each side and which one is new", () => {
    const { colours } = buildComparison(fullPlan());

    expect(colours?.before).toEqual(["black", "ivory"]);
    expect(colours?.after).toEqual(["black", "ivory", "moss"]);
    expect(colours?.added).toEqual(["moss"]);
    expect(colours?.changed).toBe(true);
  });
});

describe("buildComparison: price", () => {
  it("gives the min-max range on each side, and flags the block changed", () => {
    const { price } = buildComparison(fullPlan());

    expect(price).toEqual({
      before: { min: "349 NOK", max: "349 NOK" },
      after: { min: "379 NOK", max: "379 NOK" },
      changed: true,
    });
  });

  it("marks a below-cost row from the publish snapshot, not by comparing itself", () => {
    const below: PublishSnapshot = {
      below_cost: [{ size: "XXXL", colour: "black", price: "159 NOK", cost: "17.20 USD" }],
    };
    const withBelowCost = plan([
      stage({ stage: "render" }),
      stage({
        stage: "printify_product",
        snapshot: PRODUCT_SNAPSHOT,
        changes: [
          { kind: "price", size: "S", before: "349 NOK", after: "379 NOK", color: "black" },
        ],
      }),
      stage({ stage: "publish", blocked: "XXXL at 159 NOK is below cost", snapshot: below }),
      stage({ stage: "etsy_listing", snapshot: ETSY_LISTING_SNAPSHOT }),
      stage({ stage: "etsy_media", snapshot: ETSY_MEDIA_SNAPSHOT }),
    ]);

    const { belowCost } = buildComparison(withBelowCost);

    expect(belowCost).toEqual(below.below_cost);
  });
});

describe("buildComparison: price rows", () => {
  it("has one row per size that changed, before/after/difference", () => {
    const { priceRows } = buildComparison(fullPlan());

    const s = priceRows.find((r) => r.size === "S");
    expect(s).toEqual({
      size: "S",
      before: "349 NOK",
      after: "379 NOK",
      changed: true,
      belowCost: false,
    });
    const m = priceRows.find((r) => r.size === "M");
    expect(m?.before).toBe("349 NOK");
    expect(m?.after).toBe("379 NOK");
  });

  it("marks a row below cost when the publish snapshot names that size and colour", () => {
    const below: PublishSnapshot = {
      below_cost: [{ size: "S", colour: "black", price: "159 NOK", cost: "17.20 USD" }],
    };
    const withBelowCost = plan([
      stage({ stage: "render" }),
      stage({
        stage: "printify_product",
        snapshot: PRODUCT_SNAPSHOT,
        changes: [
          { kind: "price", size: "S", before: "349 NOK", after: "159 NOK", color: "black" },
        ],
      }),
      stage({ stage: "publish", blocked: "below cost", snapshot: below }),
      stage({ stage: "etsy_listing" }),
      stage({ stage: "etsy_media" }),
    ]);

    const { priceRows } = buildComparison(withBelowCost);

    expect(priceRows.find((r) => r.size === "S")?.belowCost).toBe(true);
  });
});

describe("buildComparison: images", () => {
  it("badges a brand-new ref, a moved one, and a removed one", () => {
    const { images } = buildComparison(fullPlan());

    expect(images?.after).toEqual([
      { rank: 1, ref: "lifestyle-02:moss", badge: "new" },
      { rank: 2, ref: "lifestyle-02:black", badge: "moved", movedFrom: 1 },
      { rank: 3, ref: "flat-lay-01:ivory", badge: "moved", movedFrom: 2 },
    ]);
    expect(images?.before).toEqual([
      { rank: 1, ref: "lifestyle-02:black", url: "https://etsy.cdn/1.jpg", badge: null },
      { rank: 2, ref: "flat-lay-01:ivory", url: "https://etsy.cdn/2.jpg", badge: null },
      { rank: 3, ref: "closeup-01:black", url: "https://etsy.cdn/3.jpg", badge: "removed" },
    ]);
    expect(images?.changed).toBe(true);
  });
});

describe("buildComparison: no Etsy listing yet", () => {
  it("reports hasEtsyListing false when the plan carries no id", () => {
    const draft = plan(
      [
        stage({ stage: "render" }),
        stage({ stage: "printify_product", snapshot: PRODUCT_SNAPSHOT }),
        stage({ stage: "publish" }),
        stage({
          stage: "etsy_listing",
          snapshot: { desired: ETSY_LISTING_SNAPSHOT.desired, live: null },
        }),
        stage({
          stage: "etsy_media",
          snapshot: { desired: ETSY_MEDIA_SNAPSHOT.desired, live: [] },
        }),
      ],
      null,
    );

    expect(buildComparison(draft).hasEtsyListing).toBe(false);
  });
});

/**
 * The `etsy_videos` block (PRD 71). Its badges come from the stage's own
 * changes -- a slot change names the ref before and after -- never from
 * comparing the snapshot's two sides here (A2).
 */
describe("buildComparison: videos", () => {
  const FEATURED = "common-media/size-guide.mp4";
  const SECOND = "./how-it-fits.mp4";

  const SNAPSHOT: EtsyVideosSnapshot = {
    desired: [
      { ref: FEATURED, file: "common-media/size-guide.mp4", after_images: null },
      { ref: SECOND, file: "listings/x/how-it-fits.mp4", after_images: 2 },
    ],
    live: [
      {
        video_id: 11,
        state: "active",
        ref: "./old.mp4",
        thumbnail_url: "https://etsy.cdn/v11.jpg",
      },
      { video_id: 12, state: "active", ref: FEATURED, thumbnail_url: "https://etsy.cdn/v12.jpg" },
    ],
  };

  function videosPlan(
    changes: Extract<StagePlanDTO["outcome"], { type: "work" }>["changes"],
    snapshot: EtsyVideosSnapshot = SNAPSHOT,
  ): PlanDTO {
    return plan([
      stage({ stage: "etsy_media", snapshot: { desired: [], live: [] } }),
      stage({ stage: "etsy_videos", group: "etsy_media", snapshot, changes }),
    ]);
  }

  it("lays out the desired videos by slot and the live ones by Etsy's thumbnail", () => {
    const { videos } = buildComparison(videosPlan([]));

    expect(videos?.after).toEqual([
      { ref: FEATURED, slot: "featured", afterImages: null, badge: null },
      { ref: SECOND, slot: "second", afterImages: 2, badge: null },
    ]);
    expect(videos?.before.map((t) => [t.videoId, t.url, t.badge])).toEqual([
      [11, "https://etsy.cdn/v11.jpg", null],
      [12, "https://etsy.cdn/v12.jpg", null],
    ]);
    expect(videos?.changed).toBe(false);
  });

  it("marks a video new, and the one it replaces removed, from the slot change's refs", () => {
    const { videos, impacts } = buildComparison(
      videosPlan([{ kind: "field", path: "videos.second", before: "./old.mp4", after: SECOND }]),
    );

    expect(videos?.after.map((t) => t.badge)).toEqual([null, "new"]);
    expect(videos?.before.map((t) => t.badge)).toEqual(["removed", null]);
    expect(videos?.changed).toBe(true);
    expect(impacts).toEqual(["Videos"]);
  });

  it("marks nothing for a swap, where both refs only change slot", () => {
    const { videos } = buildComparison(
      videosPlan([
        { kind: "field", path: "videos.featured", before: SECOND, after: FEATURED },
        { kind: "field", path: "videos.second", before: FEATURED, after: SECOND },
      ]),
    );

    expect(videos?.after.map((t) => t.badge)).toEqual([null, null]);
    expect(videos?.before.map((t) => t.badge)).toEqual([null, null]);
    expect(videos?.changed).toBe(true);
  });

  it("marks a file with new bytes new, and its upload on Etsy removed", () => {
    const { videos } = buildComparison(
      videosPlan([
        {
          kind: "field",
          path: "videos.featured.contents",
          before: "sha256:aaa",
          after: "sha256:bbb",
        },
      ]),
    );

    expect(videos?.after.map((t) => t.badge)).toEqual(["new", null]);
    expect(videos?.before.map((t) => t.badge)).toEqual([null, "removed"]);
  });

  it("marks nothing for the second video moved among the images", () => {
    const { videos } = buildComparison(
      videosPlan([{ kind: "field", path: "videos.second.after_images", before: 1, after: 2 }]),
    );

    expect(videos?.after.map((t) => t.badge)).toEqual([null, null]);
    expect(videos?.changed).toBe(true);
  });

  it("marks a foreign video removed when the stage runs, since the run sweeps it", () => {
    const foreign: EtsyVideosSnapshot = {
      ...SNAPSHOT,
      live: [{ video_id: 9, state: "inactive", ref: null, thumbnail_url: null }],
    };

    const running = buildComparison(
      videosPlan(
        [{ kind: "field", path: "videos.featured", before: null, after: FEATURED }],
        foreign,
      ),
    );
    const idle = buildComparison(videosPlan([], foreign));

    expect(running.videos?.before).toEqual([
      { videoId: 9, ref: null, url: null, inactive: true, badge: "removed" },
    ]);
    expect(idle.videos?.before.map((t) => t.badge)).toEqual([null]);
  });

  it("is null for a listing with no video on either side", () => {
    const { videos } = buildComparison(videosPlan([], { desired: [], live: [] }));
    expect(videos).toBeNull();
  });

  it("is null when the stage was not in the plan", () => {
    expect(buildComparison(fullPlan()).videos).toBeNull();
  });
});
