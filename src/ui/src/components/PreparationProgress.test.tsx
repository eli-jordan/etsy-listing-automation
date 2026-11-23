import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { PreparationJob } from "../api/preparation";
import { READY } from "../test/marigold";
import { PreparationProgress } from "./PreparationProgress";
import { preparationLabel } from "./preparationLabel";

/** A Prepare job a workspace backup holds (workspace-backup plan, decision
 * P4) says so, both in its progress and in the template rail's label. */

function queued(over: Partial<PreparationJob> = {}): PreparationJob {
  return {
    id: "job",
    template: "tee",
    kind: "prepare",
    phase: "queued",
    step: "queued",
    elapsed: 0,
    placements_completed: 0,
    config_revision: "sha256:revision",
    placements_total: 1,
    error: null,
    last_event_sequence: 1,
    queue_position: 1,
    engine_version: "engine",
    waiting_for_backup: false,
    ...over,
  };
}

describe("a Prepare job held by a backup", () => {
  it("shows waiting for backup instead of its queue place", () => {
    render(<PreparationProgress job={queued({ waiting_for_backup: true })} />);

    expect(screen.getByText("Waiting for backup")).toBeInTheDocument();
    expect(screen.queryByText(/Waiting in queue/)).not.toBeInTheDocument();
  });

  it("keeps its queue place when no backup holds it", () => {
    render(<PreparationProgress job={queued()} />);

    expect(screen.getByText("Waiting in queue · 1")).toBeInTheDocument();
  });

  it("is labelled waiting for backup on the rail", () => {
    const held = { ...READY, active_job: queued({ waiting_for_backup: true }) };

    expect(preparationLabel(held)).toBe("Waiting for backup");
    expect(preparationLabel({ ...READY, active_job: queued() })).toBe("Queued");
  });
});
