import type { RunEvent, RunPhase } from "../../types";
import {
  applyListingRunEvent,
  initialListingRunState,
  type ListingRunState,
} from "../deploy/listingRunState";

export type BatchRunSource = "review" | "apply";

export interface BatchListingState extends ListingRunState {
  listing: string;
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
    ...initialListingRunState(),
    listing,
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

function project(
  value: BatchListingState,
  event: RunEvent,
  source: BatchRunSource,
): BatchListingState {
  return {
    ...value,
    ...applyListingRunEvent(value, event, source === "review" ? "review" : "runtime-only"),
  };
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
        project(current, event, source),
      );
    }

    case "stage_planned": {
      const current = listingState(state, event.listing);
      return withListing(state, event.listing, project(current, event, source));
    }

    case "listing_planned": {
      const current = listingState(state, event.listing);
      const shouldReview = source === "review";
      const nextState =
        shouldReview && current.reviewedPlan === null
          ? { ...state, reviewedListingOrder: [...state.reviewedListingOrder, event.listing] }
          : state;
      return withListing(nextState, event.listing, project(current, event, source));
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
        project(current, event, source),
      );
    }

    case "progress": {
      const current = listingState(state, event.listing);
      const projected = project(current, event, source);
      if (projected === current) return state;
      return withListing(
        { ...state, currentListing: event.listing, currentStage: event.stage },
        event.listing,
        projected,
      );
    }

    case "stage_applied": {
      const current = listingState(state, event.listing);
      return withListing(
        { ...state, currentListing: event.listing, currentStage: event.stage },
        event.listing,
        project(current, event, source),
      );
    }

    case "stage_failed": {
      const current = listingState(state, event.listing);
      return withListing(
        { ...state, currentListing: event.listing, currentStage: event.stage },
        event.listing,
        project(current, event, source),
      );
    }

    case "listing_failed": {
      const current = listingState(state, event.listing);
      return withListing(
        { ...state, currentListing: event.listing },
        event.listing,
        project(current, event, source),
      );
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
