import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Callouts } from "./Callouts";
import { buildComparison } from "./comparison";
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

  it("shows identical Printify and Etsy drift once, attributed to Etsy", () => {
    const sameTitleDrift = {
      path: "title",
      last_applied: "Old title",
      live: "Changed title",
      last_applied_label: null,
      live_label: null,
    };
    const p = plan([
      stage({ stage: "printify_product", will_run: true, drift: [sameTitleDrift] }),
      stage({ stage: "etsy_listing", will_run: true, drift: [sameTitleDrift] }),
    ]);
    render(<Callouts plan={p} comparison={buildComparison(p)} applied={false} />);

    expect(screen.getAllByText(/Changed on Etsy since your last apply/)).toHaveLength(1);
    expect(screen.queryByText(/Changed in Printify since your last apply/)).not.toBeInTheDocument();
  });

  it("attributes Printify-only drift to Printify rather than Etsy", () => {
    const p = plan([
      stage({
        stage: "printify_product",
        will_run: true,
        drift: [{ path: "visible", last_applied: false, live: true }],
      }),
    ]);
    render(<Callouts plan={p} comparison={buildComparison(p)} applied={false} />);

    expect(screen.getByText(/Changed in Printify since your last apply/)).toBeInTheDocument();
  });

  it("collapses to a single Deployed callout once applied", () => {
    const p = plan([stage({ stage: "render", will_run: true, reason: "x" })]);
    render(<Callouts plan={p} comparison={buildComparison(p)} applied />);

    expect(screen.getByText("Deployed.")).toBeInTheDocument();
    expect(screen.queryByText("Apply will change what buyers see")).not.toBeInTheDocument();
  });
});
