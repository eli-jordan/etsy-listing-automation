import { stageBlocked, stageWillRun, type RunEvent, type RunPhase } from "../../types";
import {
  applyListingRunEvent,
  initialListingRunState,
  type ListingRunState,
} from "./listingRunState";

export type { StageRuntimeStatus } from "./listingRunState";

/**
 * Pure reducer: `RunEvent[] -> phase, per-stage runtime, plan, previews`
 * (docs/deploy-changes.md, Frontend module table).
 *
 * One rule ties every branch below to the event union `ui/runs/events.py`
 * defines: this module never decides *whether* something changed or *why* a
 * stage will run -- `stage_planned`/`listing_planned` already carry a
 * `StagePlanDTO`/`PlanDTO` the engine computed, and this only stores the
 * latest one and layers a thin "what is happening right now" overlay on top
 * (`StageRuntimeStatus`), for the three things no `Plan` can say on its own:
 * a stage mid-`apply`, its latest progress line, and a stage that failed.
 *
 * **`plan` is authoritative once known; `checkingStage` is a placeholder
 * for before it is.** A plan run's own planning walk fires `stage_checking`
 * for a stage, then `stage_planned` with that stage's resolved
 * `StagePlanDTO`, one stage at a time, in pipeline order (A21/A33 decision
 * 2) -- `checkingStage` exists only to paint the spinner on the stage being
 * examined during that walk. Once `listing_planned` arrives with the whole
 * `Plan`, that supersedes every provisional `stage_planned` seen so far,
 * because it is the same data made complete and ordered by the engine's own
 * pipeline (`STAGES`), not reassembled here.
 *
 * **An apply run replans before it applies, and this module does not care.**
 * `apply_listings` re-plans internally before `execute` runs a single stage,
 * so an apply run's event stream carries the *same* `stage_checking`/
 * `stage_planned`/`listing_planned` burst a plan run does, even though the
 * run's own `phase` stays `"applying"` throughout (`RunPhase`'s own
 * contract). Handling those events identically regardless of `phase` is
 * what makes this reducer's plan-tracking one piece of logic instead of two
 * that have to agree.
 *
 * **A stale outcome carries the plan that superseded the reviewed one.**
 * `ListingFailedEvent.stale_plan` is only set for a `StalePlanError` (A31),
 * and decision 5/9 of the doc is to *show* the fresh plan rather than the one
 * that no longer matches -- so `stale_plan`, when present, replaces `plan`
 * the same way `listing_planned` would, and `stale` records that this is
 * where it came from (so `ApplyFooter`/`DeployControl` can highlight *Plan
 * again* per the control-state table without re-deriving it from `phase`
 * alone -- `phase === "stale"` already says the same thing, but a review
 * screen re-entered from history needs the flag to travel with the plan it
 * describes, not the run's current phase).
 */

export interface DeployState extends ListingRunState {
  phase: RunPhase;
  /** Keys `${template}|${colour ?? ""}` for every scene a `preview_rendered`
   * event has named so far this run. */
  previewsRendered: Set<string>;
}

export const initialDeployState: DeployState = {
  ...initialListingRunState(),
  phase: "queued",
  previewsRendered: new Set(),
};

function previewKey(template: string, colour: string | null): string {
  return `${template}|${colour ?? ""}`;
}

/** Folds one event onto a state. Exported alongside {@link deployState}
 * (which folds a whole array from {@link initialDeployState}) because
 * `DeployPage` receives events one at a time from `runStream.ts` after the
 * initial reattach, and re-running the whole array on every event would be
 * needless for a stream that only ever grows by one. */
export function applyRunEvent(state: DeployState, event: RunEvent): DeployState {
  switch (event.type) {
    case "phase":
      return { ...state, phase: event.phase };

    case "preview_rendered":
      return {
        ...state,
        previewsRendered: new Set(state.previewsRendered).add(
          previewKey(event.template, event.colour),
        ),
      };

    default:
      return { ...state, ...applyListingRunEvent(state, event, "replace") };
  }
}

export function deployState(events: readonly RunEvent[]): DeployState {
  return events.reduce(applyRunEvent, initialDeployState);
}

/** The control-state table's own rows (docs/deploy-changes.md, the table
 * under decision 8/§7's addition) -- `"ready"` alone cannot tell Apply
 * what to do, because that depends on the *plan's* contents, not the run's
 * phase. Split out here, once, rather than recomputed by `ApplyFooter` and
 * `DeployControl` from `state.plan` each in their own words. */
export type ControlPhase =
  | "queued"
  | "planning"
  | "previewing"
  | "ready-work"
  | "ready-blocked"
  | "ready-clean"
  | "applying"
  | "applied"
  | "stale"
  | "failed"
  | "cancelled";

export function controlPhase(state: DeployState): ControlPhase {
  if (state.phase === "ready") {
    const stagePlans = state.plan?.stage_plans ?? [];
    if (stagePlans.some(stageWillRun)) return "ready-work";
    if (stagePlans.some((stage) => stageBlocked(stage) !== null)) return "ready-blocked";
    return "ready-clean";
  }
  // "planned" is the momentary hinge between the planning walk finishing and
  // the run either entering "previewing" or jumping straight to "ready" --
  // Apply is not unlockable yet either way, so it reads exactly like
  // "planning" rather than earning a fifth row the control-state table does
  // not have.
  if (state.phase === "planned") return "planning";
  return state.phase;
}
