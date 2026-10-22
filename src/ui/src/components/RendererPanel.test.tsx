import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../api/preparation";
import { READY } from "../test/marigold";
import { RendererPanel } from "./RendererPanel";

afterEach(() => vi.restoreAllMocks());

function job(kind: api.PreparationJob["kind"]): api.PreparationJob {
  return {
    id: "job",
    template: "tee",
    kind,
    phase: "running",
    step: kind === "rebuild" ? "fitting" : "normals",
    elapsed: 1,
    placements_completed: 0,
    config_revision: "sha256:revision",
    placements_total: 1,
    error: null,
    last_event_sequence: 1,
    queue_position: null,
    engine_version: "engine",
  };
}

function setup(kind: api.PreparationJob["kind"]) {
  vi.spyOn(api, "getRuntime").mockReturnValue(new Promise(() => {}));
  render(
    <RendererPanel
      settings={() => null}
      renderer={{ type: "marigold", config: {} } as never}
      onRendererChange={() => {}}
      preparation={{ ...READY, active_job: job(kind) }}
      onPrepare={() => {}}
      onCancel={() => {}}
      pending={false}
      error=""
    />,
  );
}

describe("RendererPanel", () => {
  it("shows a CPU rebuild as a spinner where the stages go, without steps or Cancel", () => {
    setup("rebuild");
    const statuses = screen.getAllByRole("status").map((s) => s.textContent);
    expect(statuses).toContain("Rebuilding maps");
    expect(screen.queryByText("Surface direction")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel preparation" })).not.toBeInTheDocument();
    expect(screen.queryByText(/You can close this browser/)).not.toBeInTheDocument();
  });

  it("keeps the staged progress and Cancel for a full GPU preparation", () => {
    setup("prepare");
    expect(screen.getByText("Surface direction")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel preparation" })).toBeInTheDocument();
  });
});
