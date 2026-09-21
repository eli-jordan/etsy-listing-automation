import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PlanDTO, StagePlanDTO } from "../../types";
import { stagePlan, type StagePlanOverrides } from "../../test/helpers";
import { BatchListingGroups } from "./BatchListingGroups";
import type { BatchListingState } from "./batchDeployState";

function stage<Name extends StagePlanDTO["stage"]>(
  stageName: Name,
  overrides: StagePlanOverrides<Name> = {},
): Extract<StagePlanDTO, { stage: Name }> {
  return stagePlan(stageName, overrides);
}

function listingState(
  listing: string,
  listingPlan: PlanDTO | null,
  overrides: Partial<BatchListingState> = {},
): BatchListingState {
  return {
    listing,
    reviewedPlan: listingPlan,
    plan: listingPlan,
    fingerprint: listingPlan === null ? null : "fingerprint",
    planFailure: null,
    failureMessage: null,
    stale: false,
    checkingStage: null,
    stageRuntime: {},
    ...overrides,
  };
}

describe("BatchListingGroups", () => {
  it("groups plans and presents per-listing impacts and runtime state", () => {
    const add: PlanDTO = {
      listing: "new-shirt",
      is_live: false,
      etsy_listing_id: null,
      stage_plans: [stage("publish", { will_run: true })],
    };
    const change: PlanDTO = {
      listing: "changed-shirt",
      is_live: true,
      etsy_listing_id: 42,
      stage_plans: [stage("publish", { will_run: true })],
    };
    const remove: PlanDTO = {
      listing: "removed-shirt",
      is_live: true,
      etsy_listing_id: 43,
      stage_plans: [stage("retract", { will_run: true })],
    };
    const onOpenListing = vi.fn();
    render(
      <BatchListingGroups
        listings={[
          listingState("new-shirt", add),
          listingState("changed-shirt", change, {
            stageRuntime: { publish: { kind: "applying", log: "saving", startedAt: 1 } },
          }),
          listingState("removed-shirt", remove, { stale: true }),
          listingState("invalid-shirt", null, { planFailure: "missing title" }),
        ]}
        onOpenListing={onOpenListing}
      />,
    );

    expect(screen.getByRole("heading", { name: /add to etsy/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /change on etsy/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /remove from etsy/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /needs attention/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /new-shirt: 1 stage/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "changed-shirt: Running" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "removed-shirt: Stale" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "invalid-shirt: missing title" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /changed-shirt/i }));

    expect(onOpenListing).toHaveBeenCalledWith("changed-shirt");
  });
});
