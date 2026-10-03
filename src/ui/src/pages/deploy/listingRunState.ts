import type { PlanDTO, RunEvent } from "../../types";

export type StageRuntimeStatus =
  | { kind: "applying"; log: string | null; startedAt: number }
  | { kind: "applied"; startedAt: number; finishedAt: number }
  | { kind: "failed"; message: string; startedAt: number; finishedAt: number };

export interface ListingRunState {
  reviewedPlan: PlanDTO | null;
  plan: PlanDTO | null;
  fingerprint: string | null;
  planFailure: string | null;
  failureMessage: string | null;
  stale: boolean;
  checkingStage: string | null;
  stageRuntime: Record<string, StageRuntimeStatus>;
}

export type ListingPlanMode = "review" | "replace" | "runtime-only";

export function initialListingRunState(): ListingRunState {
  return {
    reviewedPlan: null,
    plan: null,
    fingerprint: null,
    planFailure: null,
    failureMessage: null,
    stale: false,
    checkingStage: null,
    stageRuntime: {},
  };
}

function withRuntime(
  state: ListingRunState,
  stage: string,
  runtime: StageRuntimeStatus,
): ListingRunState {
  return { ...state, stageRuntime: { ...state.stageRuntime, [stage]: runtime } };
}

function eventTime(event: { occurred_at?: string }): number {
  const at = event.occurred_at;
  if (at === undefined) return 0;
  const parsed = Date.parse(at);
  return Number.isNaN(parsed) ? 0 : parsed;
}

/** One authoritative projection for a listing's plan and stage-runtime events.
 * Individual deploy uses `replace`; batch review uses `review`; batch apply
 * uses `runtime-only` so re-planning cannot overwrite what was reviewed. */
export function applyListingRunEvent(
  state: ListingRunState,
  event: RunEvent,
  planMode: ListingPlanMode,
): ListingRunState {
  switch (event.type) {
    case "stage_checking":
      return { ...state, checkingStage: event.stage };

    case "stage_planned":
      return {
        ...state,
        checkingStage: state.checkingStage === event.stage_plan.stage ? null : state.checkingStage,
      };

    case "listing_planned":
      if (planMode === "runtime-only") {
        return { ...state, planFailure: null, checkingStage: null };
      }
      return {
        ...state,
        reviewedPlan: planMode === "review" ? event.plan : state.reviewedPlan,
        plan: event.plan,
        fingerprint: event.fingerprint,
        planFailure: null,
        checkingStage: null,
        stale: false,
      };

    case "stage_applying":
      return withRuntime(state, event.stage, {
        kind: "applying",
        log: null,
        startedAt: eventTime(event),
      });

    case "progress": {
      const current = state.stageRuntime[event.stage];
      if (current === undefined || current.kind !== "applying") return state;
      return withRuntime(state, event.stage, { ...current, log: event.message });
    }

    case "stage_applied": {
      const finishedAt = eventTime(event);
      const current = state.stageRuntime[event.stage];
      return withRuntime(state, event.stage, {
        kind: "applied",
        startedAt: current?.kind === "applying" ? current.startedAt : finishedAt,
        finishedAt,
      });
    }

    case "stage_failed": {
      const finishedAt = eventTime(event);
      const current = state.stageRuntime[event.stage];
      return withRuntime(state, event.stage, {
        kind: "failed",
        message: event.message,
        startedAt: current?.kind === "applying" ? current.startedAt : finishedAt,
        finishedAt,
      });
    }

    case "listing_failed":
      return {
        ...state,
        failureMessage: event.message,
        planFailure: state.plan === null ? event.message : state.planFailure,
        ...(event.stale_plan
          ? { plan: event.stale_plan, stale: true, fingerprint: null, checkingStage: null }
          : {}),
      };

    default:
      return state;
  }
}
