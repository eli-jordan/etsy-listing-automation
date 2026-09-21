import { describe, expect, it } from "vitest";
import type { PlanDTO, RunEvent } from "../../types";
import { stagePlan } from "../../test/helpers";
import { batchDeployState } from "../batchDeploy/batchDeployState";
import { deployState } from "./deployState";

const renderStage = stagePlan("render", { will_run: true, reason: "render changed" });

const plan: PlanDTO = {
  listing: "alpha",
  is_live: false,
  etsy_listing_id: null,
  stage_plans: [renderStage],
};

const events: RunEvent[] = [
  { type: "stage_checking", id: 1, listing: "alpha", stage: "render" },
  { type: "stage_planned", id: 2, listing: "alpha", stage_plan: renderStage },
  { type: "listing_planned", id: 3, listing: "alpha", plan, fingerprint: "fp-alpha" },
  {
    type: "stage_applying",
    id: 4,
    listing: "alpha",
    stage: "render",
    occurred_at: "2026-09-21T10:00:00Z",
  },
  {
    type: "progress",
    id: 5,
    listing: "alpha",
    stage: "render",
    message: "rendering",
    swatches: [],
  },
  {
    type: "stage_applied",
    id: 6,
    listing: "alpha",
    stage: "render",
    occurred_at: "2026-09-21T10:00:02Z",
  },
];

describe("listingRunState", () => {
  it("gives individual and batch deploy the same per-listing projection", () => {
    const individual = deployState(events);
    const batch = batchDeployState(events).listings.alpha;

    expect(batch).toBeDefined();
    expect({
      plan: batch?.plan,
      fingerprint: batch?.fingerprint,
      planFailure: batch?.planFailure,
      failureMessage: batch?.failureMessage,
      stale: batch?.stale,
      checkingStage: batch?.checkingStage,
      stageRuntime: batch?.stageRuntime,
    }).toEqual({
      plan: individual.plan,
      fingerprint: individual.fingerprint,
      planFailure: individual.planFailure,
      failureMessage: individual.failureMessage,
      stale: individual.stale,
      checkingStage: individual.checkingStage,
      stageRuntime: individual.stageRuntime,
    });
  });

  it("keeps the reviewed batch plan immutable while apply events add runtime", () => {
    const state = batchDeployState(events.slice(0, 3), events.slice(3));
    const listing = state.listings.alpha;

    expect(listing?.reviewedPlan).toEqual(plan);
    expect(listing?.plan).toEqual(plan);
    expect(listing?.fingerprint).toBe("fp-alpha");
    expect(listing?.stageRuntime.render?.kind).toBe("applied");
  });
});
