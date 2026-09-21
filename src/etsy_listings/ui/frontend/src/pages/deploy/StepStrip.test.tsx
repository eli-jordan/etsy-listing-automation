import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { StepStrip } from "./StepStrip";
import type { StageRuntimeStatus } from "./deployState";
import type { PlanDTO, StagePlanDTO } from "../../types";
import { stagePlan, type StagePlanOverrides } from "../../test/helpers";

function stage<Name extends StagePlanDTO["stage"]>(
  overrides: StagePlanOverrides<Name> & { stage: Name },
): Extract<StagePlanDTO, { stage: Name }> {
  const { stage: stageName, ...fields } = overrides;
  return stagePlan(stageName, fields as StagePlanOverrides<Name>);
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
      render: { kind: "applied", startedAt: 1_000, finishedAt: 3_500 },
      printify_product: { kind: "applying", log: "PUT product 123", startedAt: Date.now() },
      publish: {
        kind: "failed",
        message: "Etsy rejected the request",
        startedAt: 10_000,
        finishedAt: 22_900,
      },
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
    expect(screen.getByLabelText("Elapsed 2s")).toBeInTheDocument();
    expect(screen.getByLabelText("Elapsed 12s")).toBeInTheDocument();
    expect(document.querySelector(".dv-step--running .dv-spinner")).toBeInTheDocument();
  });

  it("updates a running stage's elapsed time and stops at the recorded finish time", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-17T10:00:00Z"));
    const startedAt = Date.now();
    const { rerender } = render(
      <StepStrip
        plan={plan([stage({ stage: "publish", will_run: true, reason: "x" })])}
        stageRuntime={{ publish: { kind: "applying", log: null, startedAt } }}
        heading="What apply will do"
      />,
    );

    expect(screen.getByLabelText("Elapsed 0s")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(1_250));
    expect(screen.getByLabelText("Elapsed 1s")).toBeInTheDocument();

    rerender(
      <StepStrip
        plan={plan([stage({ stage: "publish", will_run: true, reason: "x" })])}
        stageRuntime={{ publish: { kind: "applied", startedAt, finishedAt: startedAt + 1_250 } }}
        heading="What apply did"
      />,
    );
    act(() => vi.advanceTimersByTime(5_000));
    expect(screen.getByLabelText("Elapsed 1s")).toBeInTheDocument();
    vi.useRealTimers();
  });
});
