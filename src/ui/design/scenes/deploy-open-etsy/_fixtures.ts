import type { PlanDTO } from "../../../src/types";
import type { StageRuntimeStatus } from "../../../src/pages/deploy/deployState";

export const listingName = "canary-deployments-someone-has-to-go-first";
export const etsyListingId = 4412093857;
export const printifyProductId = "6720f1c2a9e3b14d5c0e7a21";

const work = (reason: string, actions: string[]) => ({
  type: "work",
  reason,
  changes: [],
  actions: actions.map((description) => ({ description, outputs: [] })),
});
const none = { type: "work", reason: "", changes: [], actions: [] };

const renders = Array.from({ length: 13 }, (_, i) => `Render mockup ${i + 1} of 13`);

/** A first deploy: `publish` ran, so the Etsy listing is a brand-new draft. */
export const plan = {
  etsy_listing_id: null,
  stage_plans: [
    { stage: "render", drift: [], outcome: work("13 mockups", renders) },
    { stage: "printify_product", drift: [], outcome: work("New product", ["Create the Printify product"]) },
    { stage: "publish", drift: [], outcome: none },
    { stage: "etsy_listing", drift: [], outcome: none },
    { stage: "etsy_media", drift: [], outcome: work("Images", ["Upload 13 images"]) },
    { stage: "etsy_videos", group: "etsy_media", drift: [], outcome: work("Video", ["Upload 1 video"]) },
  ],
} as unknown as PlanDTO;

const t0 = 1_700_000_000_000;
const ran = (start: number, seconds: number): StageRuntimeStatus => ({
  kind: "applied",
  startedAt: t0 + start * 1000,
  finishedAt: t0 + (start + seconds) * 1000,
});

export const stageRuntime: Record<string, StageRuntimeStatus> = {
  render: ran(0, 9),
  printify_product: ran(9, 7),
  publish: ran(16, 16),
  etsy_listing: ran(32, 0),
  etsy_media: ran(32, 48),
  etsy_videos: ran(80, 31),
};

/** Shop Manager editor URL, as src/components/openOn.ts builds it. */
export const etsyUrl = `https://www.etsy.com/your/shops/me/listing-editor/edit/${etsyListingId}`;
