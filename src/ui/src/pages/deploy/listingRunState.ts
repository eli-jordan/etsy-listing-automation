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

export type ListingPlanMode =
  /** A single listing's deploy: each fresh plan replaces the one shown. */
  | "replace"
  /** A batch review: each fresh plan is also the reviewed plan. */
  | "review"
  /** A batch apply: re-planning cannot overwrite what was reviewed. */
  | "keep-reviewed";

/** Stages an apply adds by the seller's choice, which its review was planned
 * without: `etsy_activate` (`Stage.chosen_at_apply` on the server). */
const CHOSEN_AT_APPLY: ReadonlySet<string> = new Set(["etsy_activate"]);

function withStagesChosenAtApply(reviewed: PlanDTO | null, fresh: PlanDTO): PlanDTO | null {
  if (reviewed === null) return null;
  const present = new Set(reviewed.stage_plans.map((stage) => stage.stage));
  const added = fresh.stage_plans.filter(
    (stage) => CHOSEN_AT_APPLY.has(stage.stage) && !present.has(stage.stage),
  );
  return added.length === 0
    ? reviewed
    : { ...reviewed, stage_plans: [...reviewed.stage_plans, ...added] };
}

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

function startedAt(current: StageRuntimeStatus | undefined, finishedAt: number): number {
  return current?.kind === "applying" ? current.startedAt : finishedAt;
}

function withListingPlanned(
  state: ListingRunState,
  event: Extract<RunEvent, { type: "listing_planned" }>,
  planMode: ListingPlanMode,
): ListingRunState {
  if (planMode === "keep-reviewed") {
    return {
      ...state,
      plan: withStagesChosenAtApply(state.plan, event.plan),
      planFailure: null,
      checkingStage: null,
    };
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
}

function withListingFailed(
  state: ListingRunState,
  event: Extract<RunEvent, { type: "listing_failed" }>,
): ListingRunState {
  return {
    ...state,
    failureMessage: event.message,
    planFailure: state.plan === null ? event.message : state.planFailure,
    ...(event.stale_plan
      ? { plan: event.stale_plan, stale: true, fingerprint: null, checkingStage: null }
      : {}),
  };
}

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
      return withListingPlanned(state, event, planMode);

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
        startedAt: startedAt(current, finishedAt),
        finishedAt,
      });
    }

    case "stage_failed": {
      const finishedAt = eventTime(event);
      const current = state.stageRuntime[event.stage];
      return withRuntime(state, event.stage, {
        kind: "failed",
        message: event.message,
        startedAt: startedAt(current, finishedAt),
        finishedAt,
      });
    }

    case "listing_failed":
      return withListingFailed(state, event);

    default:
      return state;
  }
}
