import type { RunPhase } from "../../types";

/** Mirrors `core/application/deploy/events.py`'s `TERMINAL_PHASES` -- a run in one of these
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

/** How long a just-finished apply's result waits before it is marked seen.
 * A very small apply can finish between the user's Apply and an immediate
 * Back click; the grace lets that exit land first, so the page they return to
 * can still offer View result. Exported so tests advance exactly this far. */
export const MARK_SEEN_GRACE_MS = 750;
