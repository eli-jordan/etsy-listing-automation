import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
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

  it("warns once for all drift, linking each field and leaving its value to the row", () => {
    const p = plan([
      stage({
        stage: "etsy_listing",
        will_run: true,
        reason: "the listing's copy or settings changed",
        drift: [
          { path: "description", last_applied: "A long description.", live: "An edited one." },
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
    const onRevealDrift = vi.fn();
    render(
      <Callouts
        plan={p}
        comparison={buildComparison(p)}
        applied={false}
        onRevealDrift={onRevealDrift}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      "This listing has drifted from what’s on Etsy. 2 fields changed there since your last apply. Apply will set them back.",
    );
    expect(screen.queryByText(/A long description/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Shipping profile" }));
    expect(onRevealDrift).toHaveBeenCalledWith(
      expect.objectContaining({ key: "etsy:shipping_profile_id", expandable: false }),
    );
  });

  it("offers no field links while the comparison is off the page", () => {
    const p = plan([
      stage({
        stage: "etsy_listing",
        will_run: true,
        drift: [{ path: "title", last_applied: "Old", live: "New" }],
      }),
    ]);
    render(<Callouts plan={p} comparison={buildComparison(p)} applied={false} />);

    expect(screen.getByRole("status")).toHaveTextContent("1 field changed");
    expect(screen.queryByRole("button", { name: "Title" })).not.toBeInTheDocument();
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

    expect(screen.getByRole("status")).toHaveTextContent("what’s on Etsy. 1 field changed");
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

    expect(screen.getByRole("status")).toHaveTextContent("what’s in Printify.");
  });

  it("collapses to a single Deployed callout once applied", () => {
    const p = plan([stage({ stage: "render", will_run: true, reason: "x" })]);
    render(<Callouts plan={p} comparison={buildComparison(p)} applied />);

    expect(screen.getByText("Deployed.")).toBeInTheDocument();
    expect(screen.queryByText("Apply will change what buyers see")).not.toBeInTheDocument();
  });
});
