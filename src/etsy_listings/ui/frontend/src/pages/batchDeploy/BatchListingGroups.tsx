import type { PlanDTO } from "../../types";
import {
  buyerFacingImpacts,
  listingStageProgress,
  planGroup,
  type BatchPlanGroup,
} from "./batchDeployPresentation";
import type { BatchListingState } from "./batchDeployState";

const GROUP_LABELS: Record<BatchPlanGroup, string> = {
  add: "Add to Etsy",
  change: "Change on Etsy",
  remove: "Remove from Etsy",
  attention: "Needs attention",
};

function planFor(listing: BatchListingState): PlanDTO | null {
  return listing.plan ?? listing.reviewedPlan;
}

function rowStatus(listing: BatchListingState, plan: PlanDTO | null): string {
  if (listing.stale) return "Stale";
  if (listing.failureMessage !== null) return "Failed";
  if (plan === null || listing.planFailure !== null)
    return listing.planFailure ?? "Needs attention";

  const runnable = plan.stage_plans.filter((stage) => stage.will_run);
  if (runnable.length === 0) {
    return plan.stage_plans.some((stage) => stage.blocked !== null) ? "Blocked" : "No changes";
  }

  let completed = 0;
  let failed = 0;
  let running = false;
  for (const stage of runnable) {
    const progress = listingStageProgress(plan, listing.stageRuntime, stage.stage);
    completed += progress.completed;
    failed += progress.failed;
    running ||= progress.running > 0;
  }
  if (failed > 0) return "Failed";
  if (running) return "Running";
  if (completed === runnable.length) return "Done";
  if (completed > 0) return `${completed}/${runnable.length}`;
  return `${runnable.length} stage${runnable.length === 1 ? "" : "s"}`;
}

function ListingRow({
  listing,
  onOpenListing,
}: {
  listing: BatchListingState;
  onOpenListing: (listing: string) => void;
}) {
  const plan = planFor(listing);
  const group = planGroup(plan, listing.planFailure);
  const status = rowStatus(listing, plan);
  const impacts = plan === null ? [] : buyerFacingImpacts(plan);
  const summary = listing.planFailure ?? (impacts.length > 0 ? impacts.join(" · ") : status);

  return (
    <button
      type="button"
      className={`batch-listing-row batch-listing-row--${group}`}
      aria-label={`${listing.listing}: ${status}`}
      onClick={() => onOpenListing(listing.listing)}
    >
      <span className="batch-listing-row__copy">
        <strong>{listing.listing}</strong>
        <span className="batch-listing-row__summary">{summary}</span>
      </span>
      <span className="batch-listing-row__state">
        {listing.checkingStage !== null && <span className="dv-spinner" aria-hidden="true" />}
        <span>{status}</span>
        <span aria-hidden="true">→</span>
      </span>
    </button>
  );
}

/** The authoritative plans stay in their four review groups. This component
 * only decides how to present each already-computed state. */
export function BatchListingGroups({
  listings,
  onOpenListing,
}: {
  listings: readonly BatchListingState[];
  onOpenListing: (listing: string) => void;
}) {
  const groups = (Object.keys(GROUP_LABELS) as BatchPlanGroup[]).map((group) => ({
    group,
    listings: listings.filter(
      (listing) => planGroup(planFor(listing), listing.planFailure) === group,
    ),
  }));

  return (
    <div className="batch-listing-groups">
      {groups.map(({ group, listings: groupListings }) => (
        <section
          key={group}
          className="batch-listing-group"
          aria-labelledby={`batch-group-${group}`}
        >
          <h2 id={`batch-group-${group}`}>
            {GROUP_LABELS[group]} <span className="page-head__meta">· {groupListings.length}</span>
          </h2>
          {groupListings.length > 0 ? (
            <div className="batch-listing-group__rows">
              {groupListings.map((listing) => (
                <ListingRow key={listing.listing} listing={listing} onOpenListing={onOpenListing} />
              ))}
            </div>
          ) : (
            <p className="batch-listing-group__empty">None</p>
          )}
        </section>
      ))}
    </div>
  );
}
