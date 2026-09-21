import { describe, expect, it } from "vitest";
import type { ListingSummary, PlanDTO, StagePlanDTO } from "../../types";
import { buildComparison } from "../deploy/comparison";
import { batchDeployState, type BatchListingState } from "./batchDeployState";
import {
  aggregateStageOrder,
  aggregateStageProgress,
  batchResult,
  buyerFacingImpacts,
  candidateCounts,
  candidateNames,
  listingStageProgress,
  planGroup,
  type BatchPlanGroup,
} from "./batchDeployPresentation";

function stage(stageName: string, overrides: Partial<StagePlanDTO> = {}): StagePlanDTO {
  return {
    stage: stageName,
    will_run: false,
    changes: [],
    drift: [],
    actions: [],
    reason: null,
    blocked: null,
    snapshot: null,
    ...overrides,
  };
}

function plan(
  listing: string,
  stagePlans: StagePlanDTO[],
  etsyListingId: number | null = 1,
): PlanDTO {
  return {
    listing,
    is_live: etsyListingId !== null,
    etsy_listing_id: etsyListingId,
    stage_plans: stagePlans,
  };
}

function summary(overrides: Partial<ListingSummary> = {}): ListingSummary {
  return {
    name: "listing",
    status: "deployed",
    design: "bundled-grid",
    garment_profile: "tee",
    colour_count: 1,
    issue_counts: { block: 0, warn: 0 },
    gestures: [],
    ...overrides,
  };
}

function listingState(
  name: string,
  listingPlan: PlanDTO,
  stageRuntime: BatchListingState["stageRuntime"] = {},
): BatchListingState {
  return {
    listing: name,
    reviewedPlan: listingPlan,
    plan: listingPlan,
    fingerprint: "fp",
    planFailure: null,
    failureMessage: null,
    stale: false,
    checkingStage: null,
    stageRuntime,
  };
}

describe("candidate listing projections", () => {
  it("classifies add, edit, and remove candidates from local summaries", () => {
    const summaries = [
      summary({ name: "draft", status: "draft", etsy_listing_id: null }),
      summary({ name: "dirty", status: "dirty", etsy_listing_id: 1 }),
      summary({ name: "draft-existing", status: "draft", etsy_listing_id: 2 }),
      summary({ name: "retire", status: "pending-retire", gestures: ["retire"] }),
      summary({ name: "remove", status: "pending-delete" }),
    ];

    expect(candidateNames(summaries)).toEqual({
      add: ["draft"],
      edit: ["dirty", "draft-existing", "retire"],
      remove: ["remove"],
    });
    expect(candidateCounts([])).toEqual({ add: 0, edit: 0, remove: 0 });
  });
});

describe("plan grouping and buyer-facing impacts", () => {
  it.each<[string, PlanDTO | null, string | null, BatchPlanGroup]>([
    ["remove", plan("x", [stage("retract")]), null, "remove"],
    ["add", plan("x", [stage("render", { will_run: true })], null), null, "add"],
    ["change", plan("x", [stage("publish", { will_run: true })]), null, "change"],
    ["blocked", plan("x", [stage("publish", { blocked: "bad price" })]), null, "attention"],
    ["plan failure", null, "missing", "attention"],
  ])("classifies %s according to the returned plan", (_label, value, failure, expected) => {
    expect(planGroup(value, failure)).toBe(expected);
  });

  it("uses the existing comparison projection for buyer-facing impacts", () => {
    const value = plan("x", [
      stage("etsy_listing", {
        snapshot: {
          live: {
            title: "Old",
            description: "same",
            tags: [],
            materials: [],
            shop_section: null,
            shipping_profile: null,
          },
          desired: {
            title: "New",
            description: "same",
            tags: [],
            materials: [],
            shop_section: null,
            shipping_profile: null,
          },
        },
        changes: [{ kind: "field", path: "title", before: "Old", after: "New" }],
      }),
    ]);

    expect(buyerFacingImpacts(value)).toEqual(buildComparison(value).impacts);
    expect(buyerFacingImpacts(value)).toEqual(["Title"]);
  });
});

describe("stage projections", () => {
  it("unions stage names in engine order and puts retract after normal stages", () => {
    expect(
      aggregateStageOrder([
        plan("a", [stage("render"), stage("publish"), stage("retract")]),
        plan("b", [stage("render"), stage("future")]),
        plan("c", [stage("retract")]),
      ]),
    ).toEqual(["render", "publish", "future", "retract"]);
  });

  it("counts only runnable listings in aggregate denominators", () => {
    const alpha = plan("alpha", [stage("render", { will_run: true })]);
    const bravo = plan("bravo", [stage("render", { will_run: true })]);
    const clean = plan("clean", [stage("render")]);
    const states = [
      listingState("alpha", alpha, {
        render: { kind: "applied", startedAt: 1, finishedAt: 2 },
      }),
      listingState("bravo", bravo, {
        render: { kind: "applying", log: "rendering", startedAt: 3 },
      }),
      listingState("clean", clean),
    ];

    expect(aggregateStageProgress([alpha, bravo, clean], states, "render")).toEqual({
      total: 2,
      completed: 1,
      running: 1,
      failed: 0,
    });
    const alphaState = states[0];
    if (alphaState === undefined) throw new Error("missing alpha state");
    expect(listingStageProgress(alpha, alphaState.stageRuntime, "render")).toEqual({
      total: 1,
      completed: 1,
      running: 0,
      failed: 0,
    });
    expect(
      listingStageProgress(
        alpha,
        { render: { kind: "failed", message: "nope", startedAt: 1, finishedAt: 2 } },
        "render",
      ),
    ).toEqual({ total: 1, completed: 0, running: 0, failed: 1 });
    expect(listingStageProgress(clean, {}, "missing")).toEqual({
      total: 0,
      completed: 0,
      running: 0,
      failed: 0,
    });
  });
});

describe("batch result projection", () => {
  it("retains successes while classifying mixed failure and stale outcomes", () => {
    const review = [
      {
        type: "listing_planned",
        id: 1,
        listing: "success",
        plan: plan("success", [stage("render", { will_run: true })]),
        fingerprint: "s",
      },
      {
        type: "listing_planned",
        id: 2,
        listing: "failed",
        plan: plan("failed", [stage("render", { will_run: true })]),
        fingerprint: "f",
      },
      {
        type: "listing_planned",
        id: 3,
        listing: "stale",
        plan: plan("stale", [stage("render", { will_run: true })]),
        fingerprint: "t",
      },
    ] as const;
    const result = batchResult(
      batchDeployState(review, [
        { type: "phase", id: 4, phase: "applying" },
        { type: "stage_applying", id: 5, listing: "success", stage: "render" },
        { type: "stage_applied", id: 6, listing: "success", stage: "render" },
        { type: "listing_failed", id: 7, listing: "failed", message: "nope" },
        {
          type: "listing_failed",
          id: 8,
          listing: "stale",
          message: "changed",
          stale_plan: plan("stale", [stage("render", { will_run: false })]),
        },
        { type: "phase", id: 9, phase: "failed" },
      ]),
    );

    expect(result).toMatchObject({
      terminal: true,
      succeeded: ["success"],
      failed: ["failed"],
      stale: ["stale"],
      partial: true,
    });
  });

  it("keeps clean, blocked, attention, and pending listings distinct", () => {
    const clean = plan("clean", [stage("render")]);
    const blocked = plan("blocked", [stage("publish", { blocked: "bad price" })]);
    const pending = plan("pending", [stage("render", { will_run: true })]);
    const state = batchDeployState(
      [
        { type: "listing_planned", id: 1, listing: "clean", plan: clean, fingerprint: "c" },
        { type: "listing_planned", id: 2, listing: "blocked", plan: blocked, fingerprint: "b" },
        { type: "listing_planned", id: 3, listing: "pending", plan: pending, fingerprint: "p" },
        { type: "listing_failed", id: 4, listing: "attention", message: "invalid" },
      ],
      [{ type: "phase", id: 5, phase: "applying" }],
    );

    expect(batchResult(state)).toEqual({
      terminal: false,
      succeeded: [],
      clean: ["clean"],
      failed: [],
      stale: [],
      blocked: ["blocked"],
      attention: ["attention", "blocked"],
      pending: ["clean", "pending"],
      partial: false,
    });
  });
});
