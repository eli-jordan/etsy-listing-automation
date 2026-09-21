import type { Comparison } from "../../../src/pages/deploy/comparison";
import type { ListingDetail, ListingStatus, PlanDTO, StagePlanDTO } from "../../../src/types";
import mockupBlack from "../../assets/batch-deploy/mockup-black.png";
import mockupIvory from "../../assets/batch-deploy/mockup-ivory.png";
import mockupLifestyle from "../../assets/batch-deploy/mockup-lifestyle.png";
import mockupMoss from "../../assets/batch-deploy/mockup-moss.png";

export type BatchGroup = "add" | "change" | "remove";

export interface BatchChangeFixture {
  id: string;
  title: string;
  summary: string;
  group: BatchGroup;
  plan: PlanDTO;
  comparison: Comparison;
  detail: ListingDetail;
}

export const batchImageUrls: Record<string, string> = {
  "flat-lay:black": mockupBlack,
  "flat-lay:ivory": mockupIvory,
  "lifestyle:moss": mockupLifestyle,
  "close-up:moss": mockupMoss,
};

const pipeline = ["render", "printify_product", "publish", "etsy_listing", "etsy_media"];

function stage(
  stage: string,
  willRun: boolean,
  reason: string,
  descriptions: string[] = [],
): StagePlanDTO {
  return {
    stage,
    will_run: willRun,
    reason,
    blocked: null,
    changes: [],
    drift: [],
    snapshot: null,
    actions: descriptions.map((description) => ({
      description,
      inputs: [],
      outputs: [],
      missing_outputs: [],
    })),
  };
}

function plan(
  listing: string,
  etsyId: number | null,
  runs: Partial<Record<string, [string, string[]]>>,
): PlanDTO {
  const stages = listing === "old-logo-tee" ? ["retract"] : pipeline;
  return {
    listing,
    etsy_listing_id: etsyId,
    is_live: etsyId !== null,
    stage_plans: stages.map((name) => {
      const work = runs[name];
      return stage(name, work !== undefined, work?.[0] ?? "No changes", work?.[1] ?? []);
    }),
  };
}

function detail(name: string, status: ListingStatus, etsyId: number | null): ListingDetail {
  return {
    name,
    status,
    brief: "Fixture used by the batch deploy design prototype.",
    garment_profile: "Comfort Colors 1717",
    pricing_plan: "standard-nok",
    pricing_plan_name: "Standard NOK",
    colors: ["Black", "Ivory", "Moss"],
    design: {},
    artwork: {},
    etsy: {
      title: name,
      description: "Soft garment-dyed hiking tee.",
      tags: ["hiking", "trail"],
      materials: ["cotton"],
      shop_section: null,
      shipping_profile: null,
    },
    etsy_listing_id: etsyId,
    printify_product_id: etsyId === null ? null : `product-${etsyId}`,
    field_errors: {},
    issues: [],
    lifecycle: null,
    media: [],
    modified_at: "2026-09-18T10:00:00Z",
    price_overrides: {},
    prices: { S: "379 NOK", M: "379 NOK" },
    resolved_prices: [],
  };
}

function comparison(input: {
  hasEtsy: boolean;
  beforeTitle: string | null;
  afterTitle: string;
  beforePrice: string | null;
  afterPrice: string | null;
  beforeTags?: string[];
  afterTags?: string[];
  images?: { before: string[]; after: string[] };
}): Comparison {
  const beforeTags = input.beforeTags ?? ["hiking", "outdoors"];
  const afterTags = input.afterTags ?? beforeTags;
  const images = input.images
    ? {
        before: input.images.before.map((ref, index) => ({
          rank: index + 1,
          ref,
          url: batchImageUrls[ref] ?? null,
          badge: input.images?.after.includes(ref) ? null : ("removed" as const),
        })),
        after: input.images.after.map((ref, index) => {
          const previousIndex = input.images?.before.indexOf(ref) ?? -1;
          if (previousIndex === -1) return { rank: index + 1, ref, badge: "new" as const };
          if (previousIndex !== index) {
            return {
              rank: index + 1,
              ref,
              badge: "moved" as const,
              movedFrom: previousIndex + 1,
            };
          }
          return { rank: index + 1, ref, badge: null };
        }),
        changed: input.images.before.join() !== input.images.after.join(),
      }
    : null;
  return {
    impacts: [
      ...(images?.changed ? (["Images"] as const) : []),
      "Title",
      "Prices",
      ...(beforeTags.join() === afterTags.join() ? [] : ["Tags" as const]),
    ],
    hasEtsyListing: input.hasEtsy,
    title: {
      before: input.beforeTitle,
      after: input.afterTitle,
      changed: input.beforeTitle !== input.afterTitle,
    },
    description: null,
    tags: {
      before: beforeTags,
      after: afterTags,
      added: afterTags.filter((tag) => !beforeTags.includes(tag)),
      removed: beforeTags.filter((tag) => !afterTags.includes(tag)),
      changed: beforeTags.join() !== afterTags.join(),
    },
    materials: null,
    colours: null,
    price: {
      before:
        input.beforePrice === null ? null : { min: input.beforePrice, max: input.beforePrice },
      after: input.afterPrice === null ? null : { min: input.afterPrice, max: input.afterPrice },
      changed: input.beforePrice !== input.afterPrice,
    },
    images,
    priceRows: [],
    belowCost: [],
  };
}

export const batchChanges: BatchChangeFixture[] = [
  {
    id: "night-hike-club",
    title: "Night hike club",
    summary: "new Printify product and Etsy draft",
    group: "add",
    plan: plan("night-hike-club", null, {
      render: ["4 scenes missing", ["Render four mockup scenes"]],
      printify_product: ["Not created yet", ["Create Printify product"]],
      publish: ["Not on Etsy yet", ["Publish as an Etsy draft"]],
      etsy_listing: ["New listing fields", ["Set title, description and tags"]],
      etsy_media: ["4 images to upload", ["Upload four images in order"]],
    }),
    comparison: comparison({
      hasEtsy: false,
      beforeTitle: null,
      afterTitle: "Night Hike Club Tee",
      beforePrice: null,
      afterPrice: "349 NOK",
      beforeTags: [],
      afterTags: ["night hiking", "trail club", "outdoors"],
      images: {
        before: [],
        after: ["flat-lay:black", "flat-lay:ivory", "lifestyle:moss", "close-up:moss"],
      },
    }),
    detail: detail("Night hike club", "draft", null),
  },
  {
    id: "after-rain-trail",
    title: "After rain trail",
    summary: "new Printify product and Etsy draft",
    group: "add",
    plan: plan("after-rain-trail", null, {
      render: ["3 scenes missing", ["Render three mockup scenes"]],
      printify_product: ["Not created yet", ["Create Printify product"]],
      publish: ["Not on Etsy yet", ["Publish as an Etsy draft"]],
      etsy_listing: ["New listing fields", ["Set title, description and tags"]],
      etsy_media: ["3 images to upload", ["Upload three images in order"]],
    }),
    comparison: comparison({
      hasEtsy: false,
      beforeTitle: null,
      afterTitle: "After Rain Trail Tee",
      beforePrice: null,
      afterPrice: "349 NOK",
      beforeTags: [],
      afterTags: ["rainy trail", "hiking gift", "outdoors"],
      images: {
        before: [],
        after: ["flat-lay:ivory", "lifestyle:moss", "close-up:moss"],
      },
    }),
    detail: detail("After rain trail", "draft", null),
  },
  {
    id: "mountain-sunrise-tee",
    title: "Mountain sunrise tee",
    summary: "title, price and images",
    group: "change",
    plan: plan("mountain-sunrise-tee", 1284660101, {
      render: ["1 scene stale", ["Re-render lifestyle scene"]],
      printify_product: ["Price and title differ", ["Update title and price"]],
      etsy_listing: ["Title and price differ", ["Update Etsy title and price"]],
      etsy_media: ["1 image to add", ["Upload and reorder images"]],
    }),
    comparison: comparison({
      hasEtsy: true,
      beforeTitle: "Mountain Sunrise T-Shirt",
      afterTitle: "Mountain Sunrise Hiking Tee",
      beforePrice: "349 NOK",
      afterPrice: "379 NOK",
      images: {
        before: ["flat-lay:black", "flat-lay:ivory", "lifestyle:moss"],
        after: ["lifestyle:moss", "flat-lay:black", "close-up:moss"],
      },
    }),
    detail: detail("Mountain sunrise tee", "dirty", 1284660101),
  },
  {
    id: "cedar-trail-shirt",
    title: "Cedar trail shirt",
    summary: "colours and images",
    group: "change",
    plan: plan("cedar-trail-shirt", 1284660102, {
      render: ["2 scenes missing", ["Render forest and clay scenes"]],
      printify_product: ["2 colours to enable", ["Enable forest and clay"]],
      etsy_media: ["2 images to add", ["Upload two images"]],
    }),
    comparison: comparison({
      hasEtsy: true,
      beforeTitle: "Cedar Trail Shirt",
      afterTitle: "Cedar Trail Shirt",
      beforePrice: "329 NOK",
      afterPrice: "329 NOK",
      images: {
        before: ["flat-lay:black", "flat-lay:ivory"],
        after: ["flat-lay:black", "flat-lay:ivory", "lifestyle:moss", "close-up:moss"],
      },
    }),
    detail: detail("Cedar trail shirt", "dirty", 1284660102),
  },
  {
    id: "fjord-mornings",
    title: "Fjord mornings",
    summary: "description and tags",
    group: "change",
    plan: plan("fjord-mornings", 1284660103, {
      printify_product: ["Description differs", ["Update product description"]],
      etsy_listing: ["Description and tags differ", ["Update description and tags"]],
    }),
    comparison: comparison({
      hasEtsy: true,
      beforeTitle: "Fjord Mornings Tee",
      afterTitle: "Fjord Mornings Tee",
      beforePrice: "349 NOK",
      afterPrice: "349 NOK",
      beforeTags: ["fjord", "norway"],
      afterTags: ["fjord", "norway", "hiking", "scandinavia"],
    }),
    detail: detail("Fjord mornings", "dirty", 1284660103),
  },
  {
    id: "old-logo-tee",
    title: "Old logo tee",
    summary: "retract remote listing and remove local files",
    group: "remove",
    plan: plan("old-logo-tee", 1284660391, {
      retract: ["Marked for deletion", ["Retract Etsy listing and delete local files"]],
    }),
    comparison: comparison({
      hasEtsy: true,
      beforeTitle: "Old Logo Tee",
      afterTitle: "Removed from Etsy",
      beforePrice: "299 NOK",
      afterPrice: null,
      images: {
        before: ["flat-lay:black", "lifestyle:moss"],
        after: [],
      },
    }),
    detail: detail("Old logo tee", "pending-delete", 1284660391),
  },
];

export const batchStageOrder = [
  "render",
  "printify_product",
  "publish",
  "etsy_listing",
  "etsy_media",
  "retract",
];

export const batchStageLabels: Record<string, string> = {
  render: "Render mockups",
  printify_product: "Printify product",
  publish: "Publish to Etsy",
  etsy_listing: "Etsy listing",
  etsy_media: "Etsy images",
  retract: "Remove from Etsy",
};
