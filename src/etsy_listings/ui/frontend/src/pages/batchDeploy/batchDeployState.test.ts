import { describe, expect, it } from "vitest";
import type { PlanDTO, RunEvent, StagePlanDTO } from "../../types";
import {
  applyBatchRunEvent,
  batchDeployState,
  batchPreviewKey,
  type BatchDeployState,
  type BatchRunSource,
} from "./batchDeployState";

function listing(state: BatchDeployState, name: string) {
  const value = state.listings[name];
  if (value === undefined) throw new Error(`missing listing ${name}`);
  return value;
}

function stage(stageName: string, willRun = false): StagePlanDTO {
  return {
    stage: stageName,
    will_run: willRun,
    changes: [],
    drift: [],
    actions: [],
    reason: willRun ? "changed" : null,
    blocked: null,
    snapshot: null,
  };
}

function plan(listing: string): PlanDTO {
  return {
    listing,
    is_live: true,
    etsy_listing_id: 42,
    stage_plans: [stage("render", true), stage("publish")],
  };
}

function reviewedEvents(): RunEvent[] {
  return [
    {
      type: "phase",
      id: 1,
      phase: "planned",
      occurred_at: "2026-09-21T10:00:00.000Z",
    },
    {
      type: "stage_checking",
      id: 2,
      listing: "alpha",
      stage: "render",
    },
    {
      type: "listing_planned",
      id: 3,
      listing: "alpha",
      plan: plan("alpha"),
      fingerprint: "fp-alpha",
    },
    {
      type: "preview_rendered",
      id: 4,
      listing: "alpha",
      template: "flat-lay",
      colour: "black",
    },
    {
      type: "listing_planned",
      id: 5,
      listing: "bravo",
      plan: plan("bravo"),
      fingerprint: "fp-bravo",
    },
    {
      type: "preview_rendered",
      id: 6,
      listing: "bravo",
      template: "flat-lay",
      colour: "black",
    },
    {
      type: "phase",
      id: 7,
      phase: "ready",
      occurred_at: "2026-09-21T10:00:04.000Z",
    },
  ];
}

describe("batchDeployState", () => {
  it("keeps reviewed plans and previews scoped to their listing", () => {
    const state = batchDeployState(reviewedEvents());

    expect(state.phase).toBe("ready");
    expect(state.generatedAt).toBe("2026-09-21T10:00:00.000Z");
    expect(state.resultAt).toBeNull();
    expect(listing(state, "alpha").plan).toEqual(plan("alpha"));
    expect(listing(state, "bravo").fingerprint).toBe("fp-bravo");
    expect(state.previewsRendered).toEqual(
      new Set([
        batchPreviewKey("alpha", "flat-lay", "black"),
        batchPreviewKey("bravo", "flat-lay", "black"),
      ]),
    );
    expect(state.currentListing).toBe("alpha");
    expect(state.currentStage).toBe("render");
  });

  it("preserves reviewed listing event order for the apply request", () => {
    const state = batchDeployState([
      {
        type: "listing_planned",
        id: 1,
        listing: "10",
        plan: plan("10"),
        fingerprint: "fp-10",
      },
      {
        type: "listing_planned",
        id: 2,
        listing: "2",
        plan: plan("2"),
        fingerprint: "fp-2",
      },
    ]);

    expect(state.reviewedListingOrder).toEqual(["10", "2"]);
  });

  it("produces the same projection when events are replayed or folded live", () => {
    const events = reviewedEvents();
    const replayed = batchDeployState(events);
    const live = events.reduce(
      (state, event) => applyBatchRunEvent(state, event, "review" satisfies BatchRunSource),
      batchDeployState([]),
    );

    expect(live).toEqual(replayed);
  });

  it("overlays sequential apply progress without replacing the reviewed plan", () => {
    const review = reviewedEvents();
    const apply: RunEvent[] = [
      {
        type: "phase",
        id: 8,
        phase: "applying",
        occurred_at: "2026-09-21T10:01:00.000Z",
      },
      {
        type: "listing_planned",
        id: 8.5,
        listing: "alpha",
        plan: plan("alpha"),
        fingerprint: "fp-new-but-not-reviewed",
      },
      {
        type: "stage_applying",
        id: 9,
        listing: "alpha",
        stage: "render",
        occurred_at: "2026-09-21T10:01:01.000Z",
      },
      {
        type: "stage_applied",
        id: 10,
        listing: "alpha",
        stage: "render",
        occurred_at: "2026-09-21T10:01:03.000Z",
      },
      {
        type: "stage_applying",
        id: 11,
        listing: "bravo",
        stage: "render",
        occurred_at: "2026-09-21T10:01:04.000Z",
      },
      {
        type: "stage_failed",
        id: 12,
        listing: "bravo",
        stage: "render",
        message: "render failed",
        occurred_at: "2026-09-21T10:01:05.000Z",
      },
      {
        type: "listing_failed",
        id: 13,
        listing: "bravo",
        message: "render failed",
      },
      {
        type: "phase",
        id: 14,
        phase: "failed",
        occurred_at: "2026-09-21T10:01:06.000Z",
      },
    ];

    const state = batchDeployState(review, apply);

    expect(state.phase).toBe("failed");
    expect(state.resultAt).toBe("2026-09-21T10:01:06.000Z");
    expect(listing(state, "alpha").plan).toEqual(plan("alpha"));
    expect(listing(state, "alpha").reviewedPlan).toEqual(plan("alpha"));
    expect(listing(state, "alpha").fingerprint).toBe("fp-alpha");
    expect(listing(state, "alpha").stageRuntime.render).toMatchObject({ kind: "applied" });
    expect(listing(state, "bravo").stageRuntime.render).toMatchObject({
      kind: "failed",
      message: "render failed",
    });
    expect(state.currentListing).toBe("bravo");
    expect(state.currentStage).toBe("render");
  });

  it("does not invent a reviewed plan from apply re-planning", () => {
    const state = batchDeployState(
      [],
      [
        {
          type: "listing_planned",
          id: 1,
          listing: "alpha",
          plan: plan("alpha"),
          fingerprint: "fp-alpha",
        },
      ],
    );

    expect(listing(state, "alpha").reviewedPlan).toBeNull();
    expect(listing(state, "alpha").plan).toBeNull();
    expect(listing(state, "alpha").fingerprint).toBeNull();
  });

  it("keeps a fresh stale plan separate from the reviewed fingerprint", () => {
    const fresh = plan("alpha");
    const state = batchDeployState(reviewedEvents(), [
      {
        type: "listing_failed",
        id: 8,
        listing: "alpha",
        message: "alpha changed since review",
        stale_plan: fresh,
      },
    ]);

    expect(listing(state, "alpha").reviewedPlan).toEqual(plan("alpha"));
    expect(listing(state, "alpha").plan).toEqual(fresh);
    expect(listing(state, "alpha").fingerprint).toBeNull();
    expect(listing(state, "alpha").stale).toBe(true);
  });

  it("retains a planning failure even though no plan exists for that listing", () => {
    const state = batchDeployState([
      {
        type: "listing_failed",
        id: 1,
        listing: "missing",
        message: "listing is invalid",
      },
    ]);

    expect(listing(state, "missing").plan).toBeNull();
    expect(listing(state, "missing").planFailure).toBe("listing is invalid");
    expect(listing(state, "missing").failureMessage).toBe("listing is invalid");
  });

  it("records progress and terminal stage events without using the wall clock", () => {
    const state = batchDeployState(
      [],
      [
        {
          type: "progress",
          id: 1,
          listing: "alpha",
          stage: null,
          message: "ignored without a stage",
          swatches: [],
        },
        {
          type: "progress",
          id: 2,
          listing: "alpha",
          stage: "render",
          message: "ignored before applying",
          swatches: [],
        },
        { type: "stage_applying", id: 3, listing: "alpha", stage: "render" },
        {
          type: "progress",
          id: 4,
          listing: "alpha",
          stage: "render",
          message: "rendering",
          swatches: [],
        },
        { type: "stage_applied", id: 5, listing: "alpha", stage: "render" },
        {
          type: "stage_failed",
          id: 6,
          listing: "alpha",
          stage: "publish",
          message: "publish failed",
        },
      ],
    );

    expect(listing(state, "alpha").stageRuntime.render).toEqual({
      kind: "applied",
      startedAt: 0,
      finishedAt: 0,
    });
    expect(listing(state, "alpha").stageRuntime.publish).toEqual({
      kind: "failed",
      message: "publish failed",
      startedAt: 0,
      finishedAt: 0,
    });
    expect(state.currentListing).toBe("alpha");
    expect(state.currentStage).toBe("publish");
  });
});
