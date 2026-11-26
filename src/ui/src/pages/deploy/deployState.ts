import { stageBlocked, stageWillRun, type RunEvent, type RunPhase } from "../../types";
import {
  applyListingRunEvent,
  initialListingRunState,
  type ListingRunState,
} from "./listingRunState";

export type { StageRuntimeStatus } from "./listingRunState";

export interface DeployState extends ListingRunState {
  phase: RunPhase;
  /** `previewKey`s of the scenes this run's `preview_rendered` events named. */
  previewsRendered: Set<string>;
}

export const initialDeployState: DeployState = {
  ...initialListingRunState(),
  phase: "queued",
  previewsRendered: new Set(),
};

export function previewKey(template: string, colour: string | null): string {
  return `${template}|${colour ?? ""}`;
}

/** The state an apply starts from: the reviewed plan stays on screen until
 * the apply's own re-plan sends a fresh `listing_planned`. */
export function applyStarted(state: DeployState): DeployState {
  return { ...initialDeployState, plan: state.plan, fingerprint: state.fingerprint };
}

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

export function controlPhase(state: DeployState, publish = false): ControlPhase {
  if (state.phase === "ready") {
    const stagePlans = state.plan?.stage_plans ?? [];
    if (stagePlans.some(stageWillRun)) return "ready-work";
    if (publish && state.plan?.publishable === true) return "ready-work";
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
