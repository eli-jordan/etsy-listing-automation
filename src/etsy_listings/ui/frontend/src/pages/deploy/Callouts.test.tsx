import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Callouts } from "./Callouts";
import { buildComparison } from "./comparison";
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

describe("Callouts", () => {
  it("shows a green callout when nothing will run and nothing is blocked", () => {
    const p = plan([stage({ stage: "render" }), stage({ stage: "publish" })]);
    render(<Callouts plan={p} comparison={buildComparison(p)} applied={false} />);

    expect(screen.getByText("Nothing to deploy.")).toBeInTheDocument();
  });

  it("shows the positive headline when at least one stage will run, even if another is blocked", () => {
    const p = plan([
      stage({ stage: "render", will_run: true, reason: "referenced scenes changed" }),
      stage({ stage: "publish", blocked: "XXXL at 159 NOK is below cost.\nRaise the price." }),
    ]);
    render(<Callouts plan={p} comparison={buildComparison(p)} applied={false} />);

    expect(screen.getByText("Apply will change what buyers see")).toBeInTheDocument();
    expect(screen.getByText("XXXL at 159 NOK is below cost.")).toBeInTheDocument();
    expect(screen.getByText("Raise the price.")).toBeInTheDocument();
  });

  it("shows the negative headline only when nothing at all can run", () => {
    const p = plan([stage({ stage: "publish", blocked: "no shop configured" })]);
    render(<Callouts plan={p} comparison={buildComparison(p)} applied={false} />);

    expect(screen.getByText("This deploy can’t go ahead yet")).toBeInTheDocument();
    expect(screen.queryByText("Apply will change what buyers see")).not.toBeInTheDocument();
  });

  it("shows a drift callout naming both sides, from the stage's own labels", () => {
    const p = plan([
      stage({
        stage: "etsy_listing",
        will_run: true,
        reason: "the listing's copy or settings changed",
        drift: [
          {
            path: "shipping_profile_id",
            last_applied: 19283,
            live: 20011,
            last_applied_label: "Norway standard",
            live_label: "Printify default",
          },
        ],
      }),
    ]);
    render(<Callouts plan={p} comparison={buildComparison(p)} applied={false} />);

    expect(screen.getByText(/Printify default/)).toBeInTheDocument();
    expect(screen.getByText(/Norway standard/)).toBeInTheDocument();
    expect(screen.queryByText(/19283/)).not.toBeInTheDocument();
  });

  it("collapses to a single Deployed callout once applied", () => {
    const p = plan([stage({ stage: "render", will_run: true, reason: "x" })]);
    render(<Callouts plan={p} comparison={buildComparison(p)} applied />);

    expect(screen.getByText("Deployed.")).toBeInTheDocument();
    expect(screen.queryByText("Apply will change what buyers see")).not.toBeInTheDocument();
  });
});
