import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PlanDTO, StagePlanDTO } from "../../types";
import { BatchAggregateStages } from "./BatchAggregateStages";
import type { BatchListingState } from "./batchDeployState";

function stage(stageName: StagePlanDTO["stage"], willRun = false): StagePlanDTO {
  return {
    stage: stageName,
    will_run: willRun,
    changes: [],
    drift: [],
    actions: [],
    reason: null,
    blocked: null,
    snapshot: null,
  };
}

function plan(listing: string, stages: StagePlanDTO[]): PlanDTO {
  return { listing, is_live: true, etsy_listing_id: 1, stage_plans: stages };
}

function listingState(
  listing: string,
  listingPlan: PlanDTO,
  stageRuntime: BatchListingState["stageRuntime"],
): BatchListingState {
  return {
    listing,
    reviewedPlan: listingPlan,
    plan: listingPlan,
    fingerprint: "fingerprint",
    planFailure: null,
    failureMessage: null,
    stale: false,
    checkingStage: null,
    stageRuntime,
  };
}

describe("BatchAggregateStages", () => {
  it("shows authoritative progress and lets the current listing open its drawer", () => {
    const renderPlan = plan("alpha", [stage("render", true), stage("publish")]);
    const publishPlan = plan("bravo", [stage("render", true), stage("publish", true)]);
    const onOpenListing = vi.fn();
    render(
      <BatchAggregateStages
        plans={[renderPlan, publishPlan]}
        listings={[
          listingState("alpha", renderPlan, {
            render: { kind: "applied", startedAt: 1, finishedAt: 2 },
          }),
          listingState("bravo", publishPlan, {
            publish: { kind: "applying", log: "updating", startedAt: 3 },
          }),
        ]}
        onOpenListing={onOpenListing}
      />,
    );

    expect(screen.getByText("Render mockups")).toBeInTheDocument();
    expect(screen.getByText("1/2")).toBeInTheDocument();
    expect(screen.getByText("Publish to Etsy")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /running · bravo/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /running · bravo/i }));

    expect(onOpenListing).toHaveBeenCalledWith("bravo");
  });

  it("keeps a stage with no runnable plans visible as up to date", () => {
    render(
      <BatchAggregateStages
        plans={[plan("clean", [stage("render")])]}
        listings={[listingState("clean", plan("clean", [stage("render")]), {})]}
        onOpenListing={vi.fn()}
      />,
    );

    expect(screen.getByText("0/0")).toBeInTheDocument();
    expect(screen.getByText("No listings will run")).toBeInTheDocument();
  });

  it("links a failed stage tile to the affected listing", () => {
    const renderPlan = plan("alpha", [stage("render", true)]);
    const onOpenListing = vi.fn();
    render(
      <BatchAggregateStages
        plans={[renderPlan]}
        listings={[
          listingState("alpha", renderPlan, {
            render: {
              kind: "failed",
              message: "render failed",
              startedAt: 1,
              finishedAt: 2,
            },
          }),
        ]}
        onOpenListing={onOpenListing}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /attention · alpha/i }));

    expect(onOpenListing).toHaveBeenCalledWith("alpha");
  });
});
