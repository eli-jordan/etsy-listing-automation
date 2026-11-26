import type { RunSummary } from "../../types";
import { TERMINAL_PHASES } from "../deploy/runPhases";

export interface ReviewRunAction {
  label: string;
  prefix: string;
}

export function reviewRunAction(run: RunSummary | null): ReviewRunAction | null {
  if (run === null) return null;
  if (!TERMINAL_PHASES.has(run.phase)) {
    return {
      label: "View batch progress",
      prefix: run.kind === "apply" ? "Deploying…" : "Planning…",
    };
  }
  return run.seen ? null : unseenRunAction(run);
}

function unseenRunAction(run: RunSummary): ReviewRunAction | null {
  if (run.kind === "apply" && run.phase === "applied") {
    return { label: "View batch result", prefix: "Deployed ✓" };
  }
  if (run.kind === "apply" && run.phase === "stale") {
    return { label: "View batch result", prefix: "Deploy failed" };
  }
  if (run.phase === "ready") return { label: "View batch review", prefix: "Review ready" };
  if (run.phase === "failed") return { label: "View batch result", prefix: "Deploy failed" };
  return null;
}
