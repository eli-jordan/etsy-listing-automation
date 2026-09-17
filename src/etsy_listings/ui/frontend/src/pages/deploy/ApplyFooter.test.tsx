import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApplyFooter } from "./ApplyFooter";

/**
 * The bottom bar's note and Apply's enabled/disabled/spinner state, one case
 * per row of the control-state table (docs/deploy-changes.md, §7's addition
 * plus the three new rows). `applied` gets its own component state (a
 * "Back" button in place of Apply), covered separately below.
 */

describe("ApplyFooter: footer notes per control phase", () => {
  it.each([
    ["queued", "Waiting for another run to finish."],
    ["planning", "Apply unlocks once the plan is ready."],
    ["ready-blocked", "Nothing can run until the blocked step is fixed."],
    ["ready-clean", "There is nothing to apply."],
    ["applying", "Running steps in order. You can leave; this keeps going."],
    ["failed", "Apply stopped at a failed step. Plan again to continue."],
    [
      "stale",
      "This listing changed after it was planned. Plan again to review the current version.",
    ],
  ] as const)("phase %s reads %j", (phase, note) => {
    render(
      <ApplyFooter controlPhase={phase} previewsTotal={0} previewsDone={0} onApply={() => {}} />,
    );
    expect(screen.getByText(note)).toBeInTheDocument();
  });

  it("counts previews still rendering", () => {
    render(
      <ApplyFooter
        controlPhase="previewing"
        previewsTotal={4}
        previewsDone={2}
        onApply={() => {}}
      />,
    );
    expect(screen.getByText("Rendering previews (2 of 4)…")).toBeInTheDocument();
  });

  it("ready-work explains that a later edit means planning again", () => {
    render(
      <ApplyFooter
        controlPhase="ready-work"
        previewsTotal={0}
        previewsDone={0}
        onApply={() => {}}
      />,
    );
    expect(screen.getByText(/Apply runs exactly this plan/)).toBeInTheDocument();
  });
});

describe("ApplyFooter: the Apply button", () => {
  it("is enabled only when there is runnable work and nothing is left previewing", () => {
    render(
      <ApplyFooter
        controlPhase="ready-work"
        previewsTotal={0}
        previewsDone={0}
        onApply={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "Apply" })).toBeEnabled();
  });

  it.each([
    "queued",
    "planning",
    "previewing",
    "ready-blocked",
    "ready-clean",
    "stale",
    "failed",
  ] as const)("is disabled in %s", (phase) => {
    render(
      <ApplyFooter controlPhase={phase} previewsTotal={1} previewsDone={0} onApply={() => {}} />,
    );
    expect(screen.getByRole("button", { name: /Apply/ })).toBeDisabled();
  });

  it("shows a spinner and stays disabled while applying", () => {
    render(
      <ApplyFooter controlPhase="applying" previewsTotal={0} previewsDone={0} onApply={() => {}} />,
    );
    const button = screen.getByRole("button", { name: /Applying/ });
    expect(button).toBeDisabled();
  });

  it("calls onApply when clicked in the ready-work state", async () => {
    const onApply = vi.fn();
    render(
      <ApplyFooter
        controlPhase="ready-work"
        previewsTotal={0}
        previewsDone={0}
        onApply={onApply}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(onApply).toHaveBeenCalledOnce();
  });
});

describe("ApplyFooter: applied", () => {
  it("shows what was deployed and a way back, with no Apply button", () => {
    const onBack = vi.fn();
    render(
      <ApplyFooter
        controlPhase="applied"
        previewsTotal={0}
        previewsDone={0}
        onApply={() => {}}
        appliedStepCount={3}
        backLabel="← Back to editor"
        onBack={onBack}
      />,
    );
    expect(screen.getByText("Deployed 3 steps.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apply" })).not.toBeInTheDocument();
    screen.getByRole("button", { name: "← Back to editor" }).click();
    expect(onBack).toHaveBeenCalledOnce();
  });

  it("uses singular step wording for exactly one step", () => {
    render(
      <ApplyFooter
        controlPhase="applied"
        previewsTotal={0}
        previewsDone={0}
        onApply={() => {}}
        appliedStepCount={1}
        backLabel="← Back to editor"
        onBack={() => {}}
      />,
    );
    expect(screen.getByText("Deployed 1 step.")).toBeInTheDocument();
  });
});
