import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StepStrip } from "./StepStrip";
import type { StageRuntimeStatus } from "./deployState";
import type { PlanDTO, StagePlanDTO } from "../../types";

function stage(overrides: Partial<StagePlanDTO> & { stage: string }): StagePlanDTO {
  return {
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

function plan(stagePlans: StagePlanDTO[]): PlanDTO {
  return { listing: "x", is_live: true, etsy_listing_id: 1, stage_plans: stagePlans };
}

describe("StepStrip", () => {
  it("draws exactly the stages the plan returned, in order -- one for a retract-only plan", () => {
    render(
      <StepStrip
        plan={plan([stage({ stage: "retract", will_run: true, reason: "marked for deletion" })])}
        stageRuntime={{}}
        heading="What apply will do"
      />,
    );

    expect(screen.getByText("Remove from Etsy")).toBeInTheDocument();
    expect(screen.getByText("marked for deletion")).toBeInTheDocument();
    expect(screen.queryByText("Render mockups")).not.toBeInTheDocument();
  });

  it("shows a stage with no changes as skipped, and a blocked one as blocked", () => {
    render(
      <StepStrip
        plan={plan([
          stage({ stage: "render", will_run: false }),
          stage({ stage: "publish", blocked: "below cost\nraise the price" }),
        ])}
        stageRuntime={{}}
        heading="What apply will do"
      />,
    );

    expect(screen.getByText("No changes")).toBeInTheDocument();
    expect(screen.getByText("Blocked")).toBeInTheDocument();
  });

  it("overlays applying/applied/failed from stageRuntime over the static plan", () => {
    const runtime: Record<string, StageRuntimeStatus> = {
      render: { kind: "applied" },
      printify_product: { kind: "applying", log: "PUT product 123" },
      publish: { kind: "failed", message: "Etsy rejected the request" },
    };
    render(
      <StepStrip
        plan={plan([
          stage({ stage: "render", will_run: true, reason: "x" }),
          stage({ stage: "printify_product", will_run: true, reason: "y" }),
          stage({ stage: "publish", will_run: true, reason: "z" }),
          stage({ stage: "etsy_listing", will_run: true, reason: "w" }),
        ])}
        stageRuntime={runtime}
        heading="What apply did"
      />,
    );

    expect(screen.getByText("Done")).toBeInTheDocument();
    expect(
      screen.getByText((_, node) => node?.textContent === "› PUT product 123"),
    ).toBeInTheDocument();
    expect(screen.getByText("Etsy rejected the request")).toBeInTheDocument();
    // etsy_listing was never reached because publish failed before it.
    expect(screen.getByText("Not reached")).toBeInTheDocument();
  });
});
