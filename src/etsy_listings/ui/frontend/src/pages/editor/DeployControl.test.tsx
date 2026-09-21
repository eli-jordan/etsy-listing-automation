import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as runsApi from "../../api/runs";
import type { RunSummary } from "../../types";
import { runSummary, type RunSummaryOverrides } from "../../test/helpers";
import { DeployControl } from "./DeployControl";

/**
 * The page-head control's four states (docs/deploy-changes.md decision 8).
 */

function summary(over: RunSummaryOverrides = {}): RunSummary {
  return runSummary({
    id: "run-1",
    kind: "apply",
    phase: "applied",
    created_at: "2026-09-17T10:00:00Z",
    ...over,
  });
}

function renderControl(flush = vi.fn().mockResolvedValue(undefined)) {
  return {
    flush,
    ...render(
      <MemoryRouter initialEntries={["/listings/take-a-hike"]}>
        <Routes>
          <Route
            path="/listings/:name"
            element={<DeployControl name="take-a-hike" flush={flush} />}
          />
          <Route path="/listings/:name/deploy" element={<p>deploy view</p>} />
        </Routes>
      </MemoryRouter>,
    ),
  };
}

afterEach(() => vi.restoreAllMocks());

describe("DeployControl", () => {
  it("offers to deploy when this listing has no run", async () => {
    vi.spyOn(runsApi, "currentRun").mockResolvedValue(null);
    renderControl();

    expect(await screen.findByRole("button", { name: /Deploy changes/ })).toBeInTheDocument();
  });

  it("offers to deploy again once a finished run has been seen", async () => {
    vi.spyOn(runsApi, "currentRun").mockResolvedValue(summary({ phase: "applied", seen: true }));
    renderControl();

    expect(await screen.findByRole("button", { name: /Deploy changes/ })).toBeInTheDocument();
  });

  it("treats a cancelled run as nothing to reattach to", async () => {
    vi.spyOn(runsApi, "currentRun").mockResolvedValue(
      summary({ kind: "plan", phase: "cancelled" }),
    );
    renderControl();

    expect(await screen.findByRole("button", { name: /Deploy changes/ })).toBeInTheDocument();
  });

  it.each(["queued", "planning", "previewing", "applying", "ready"] as const)(
    "offers to view progress while a run is under way (%s)",
    async (phase) => {
      vi.spyOn(runsApi, "currentRun").mockResolvedValue(
        summary({ kind: phase === "applying" ? "apply" : "plan", phase }),
      );
      renderControl();

      expect(
        await screen.findByRole("button", { name: /Deploying… View progress →/ }),
      ).toBeInTheDocument();
    },
  );

  it("reads Deployed for an unseen successful apply", async () => {
    vi.spyOn(runsApi, "currentRun").mockResolvedValue(summary({ phase: "applied", seen: false }));
    renderControl();

    expect(
      await screen.findByRole("button", { name: /Deployed .* View result/ }),
    ).toBeInTheDocument();
  });

  it.each(["failed", "stale"] as const)(
    "reads Deploy failed for an unseen %s apply",
    async (phase) => {
      vi.spyOn(runsApi, "currentRun").mockResolvedValue(summary({ phase, seen: false }));
      renderControl();

      expect(await screen.findByRole("button", { name: /Deploy failed/ })).toBeInTheDocument();
    },
  );

  it("saves the pending edit before navigating to the deploy route", async () => {
    vi.spyOn(runsApi, "currentRun").mockResolvedValue(null);
    const { flush } = renderControl();

    await userEvent.click(await screen.findByRole("button", { name: /Deploy changes/ }));

    expect(flush).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.getByText("deploy view")).toBeInTheDocument());
  });
});
