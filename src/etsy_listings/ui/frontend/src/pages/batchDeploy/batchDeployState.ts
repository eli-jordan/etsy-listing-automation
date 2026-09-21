import type { PlanDTO, RunEvent, RunPhase } from "../../types";
import type { StageRuntimeStatus } from "../deploy/deployState";

export type BatchRunSource = "review" | "apply";

export interface BatchListingState {
  listing: string;
  /** The plan the seller reviewed. */
  reviewedPlan: PlanDTO | null;
  /** The effective plan to show for this row. A stale outcome may replace it
   * with the fresh plan returned by the engine. */
  plan: PlanDTO | null;
  fingerprint: string | null;
  planFailure: string | null;
  failureMessage: string | null;
  stale: boolean;
  checkingStage: string | null;
  stageRuntime: Record<string, StageRuntimeStatus>;
}

export interface BatchDeployState {
  phase: RunPhase;
  applyStarted: boolean;
  /** Phase timestamps are copied verbatim from the event log, never generated
   * while folding, so replay and live delivery produce the same state. */
  phaseTimes: Partial<Record<RunPhase, string>>;
  generatedAt: string | null;
  resultAt: string | null;
  /** The event order the backend used for the reviewed apply set. A Record's
   * property order is not enough here: integer-like listing names are sorted
   * numerically by JavaScript, while the API validates the ordered set. */
  reviewedListingOrder: string[];
  listings: Record<string, BatchListingState>;
  previewsRendered: Set<string>;
  currentListing: string | null;
  currentStage: string | null;
}

export const initialBatchDeployState: BatchDeployState = {
  phase: "queued",
  applyStarted: false,
  phaseTimes: {},
  generatedAt: null,
  resultAt: null,
  reviewedListingOrder: [],
  listings: {},
  previewsRendered: new Set(),
  currentListing: null,
  currentStage: null,
};

export function batchPreviewKey(listing: string, template: string, colour: string | null): string {
  return `${listing}|${template}|${colour ?? ""}`;
}

function emptyListing(listing: string): BatchListingState {
  return {
    listing,
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

function listingState(state: BatchDeployState, listing: string): BatchListingState {
  return state.listings[listing] ?? emptyListing(listing);
}

function withListing(state: BatchDeployState, listing: string, value: BatchListingState) {
  return { ...state, listings: { ...state.listings, [listing]: value } };
}

function eventTime(event: RunEvent): string | null {
  return "occurred_at" in event && typeof event.occurred_at === "string" ? event.occurred_at : null;
}

function withPhase(state: BatchDeployState, phase: RunPhase, at: string | null) {
  const phaseTimes = at === null ? state.phaseTimes : { ...state.phaseTimes, [phase]: at };
  const generatedAt =
    phase === "planned" || phase === "ready" ? (state.generatedAt ?? at) : state.generatedAt;
  const resultAt =
    phase === "applied" || phase === "failed" || phase === "stale" || phase === "cancelled"
      ? (at ?? state.resultAt)
      : state.resultAt;
  return { ...state, phase, phaseTimes, generatedAt, resultAt };
}

function withRuntime(
  value: BatchListingState,
  stage: string,
  runtime: StageRuntimeStatus,
): BatchListingState {
  return { ...value, stageRuntime: { ...value.stageRuntime, [stage]: runtime } };
}

function runtimeTime(event: RunEvent): number {
  const at = eventTime(event);
  return at === null ? 0 : Date.parse(at);
}

/** Fold one recorded event. `source` distinguishes the reviewed plan from the
 * apply overlay; apply re-planning is deliberately not allowed to replace a
 * reviewed plan unless it is the explicit fresh plan on a stale failure. */
export function applyBatchRunEvent(
  state: BatchDeployState,
  event: RunEvent,
  source: BatchRunSource,
): BatchDeployState {
  if (source === "apply" && !state.applyStarted) {
    state = { ...state, applyStarted: true };
  }

  switch (event.type) {
    case "phase":
      return withPhase(state, event.phase, eventTime(event));

    case "stage_checking": {
      const current = listingState(state, event.listing);
      return withListing(
        { ...state, currentListing: event.listing, currentStage: event.stage },
        event.listing,
        { ...current, checkingStage: event.stage },
      );
    }

    case "stage_planned": {
      const current = listingState(state, event.listing);
      return withListing(state, event.listing, {
        ...current,
        checkingStage:
          current.checkingStage === event.stage_plan.stage ? null : current.checkingStage,
      });
    }

    case "listing_planned": {
      const current = listingState(state, event.listing);
      const shouldReview = source === "review";
      const nextState =
        shouldReview && current.reviewedPlan === null
          ? { ...state, reviewedListingOrder: [...state.reviewedListingOrder, event.listing] }
          : state;
      return withListing(nextState, event.listing, {
        ...current,
        ...(shouldReview
          ? { reviewedPlan: event.plan, plan: event.plan, fingerprint: event.fingerprint }
          : {}),
        planFailure: null,
        checkingStage: null,
      });
    }

    case "preview_rendered":
      return {
        ...state,
        previewsRendered: new Set(state.previewsRendered).add(
          batchPreviewKey(event.listing, event.template, event.colour),
        ),
      };

    case "stage_applying": {
      const current = listingState(state, event.listing);
      return withListing(
        { ...state, currentListing: event.listing, currentStage: event.stage },
        event.listing,
        withRuntime(current, event.stage, {
          kind: "applying",
          log: null,
          startedAt: runtimeTime(event),
        }),
      );
    }

    case "progress": {
      if (event.stage === null) return state;
      const current = listingState(state, event.listing);
      const runtime = current.stageRuntime[event.stage];
      if (runtime === undefined || runtime.kind !== "applying") return state;
      return withListing(
        { ...state, currentListing: event.listing, currentStage: event.stage },
        event.listing,
        withRuntime(current, event.stage, { ...runtime, log: event.message }),
      );
    }

    case "stage_applied": {
      const current = listingState(state, event.listing);
      const previous = current.stageRuntime[event.stage];
      const finishedAt = runtimeTime(event);
      return withListing(
        { ...state, currentListing: event.listing, currentStage: event.stage },
        event.listing,
        withRuntime(current, event.stage, {
          kind: "applied",
          startedAt: previous?.kind === "applying" ? previous.startedAt : finishedAt,
          finishedAt,
        }),
      );
    }

    case "stage_failed": {
      const current = listingState(state, event.listing);
      const previous = current.stageRuntime[event.stage];
      const finishedAt = runtimeTime(event);
      return withListing(
        { ...state, currentListing: event.listing, currentStage: event.stage },
        event.listing,
        withRuntime(current, event.stage, {
          kind: "failed",
          message: event.message,
          startedAt: previous?.kind === "applying" ? previous.startedAt : finishedAt,
          finishedAt,
        }),
      );
    }

    case "listing_failed": {
      const current = listingState(state, event.listing);
      const next = {
        ...current,
        failureMessage: event.message,
        planFailure: current.plan === null ? event.message : current.planFailure,
        ...(event.stale_plan
          ? { plan: event.stale_plan, stale: true, fingerprint: null, checkingStage: null }
          : {}),
      };
      return withListing({ ...state, currentListing: event.listing }, event.listing, next);
    }

    default:
      return state;
  }
}

export function batchDeployState(
  reviewEvents: readonly RunEvent[],
  applyEvents: readonly RunEvent[] = [],
): BatchDeployState {
  const reviewed = reviewEvents.reduce(
    (state, event) => applyBatchRunEvent(state, event, "review"),
    initialBatchDeployState,
  );
  return applyEvents.reduce((state, event) => applyBatchRunEvent(state, event, "apply"), reviewed);
}
