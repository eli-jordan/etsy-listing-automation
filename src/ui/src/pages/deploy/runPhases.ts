import type { RunPhase } from "../../types";

/** Mirrors `ui/runs/events.py`'s `TERMINAL_PHASES` -- a run in one of these
 * will never emit another event. `DeployPage` uses it to decide whether a
 * run found on mount is still active (open the SSE stream) or already
 * finished (rebuild statically, decision 9). */
export const TERMINAL_PHASES: ReadonlySet<RunPhase> = new Set([
  "ready",
  "applied",
  "failed",
  "stale",
  "cancelled",
]);
