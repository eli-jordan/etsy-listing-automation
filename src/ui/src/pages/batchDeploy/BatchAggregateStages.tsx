import { STAGE_LABELS, stageWillRun } from "../../types";
import {
  aggregateStageOrder,
  aggregateStageProgress,
  type StageProgress,
} from "./batchDeployPresentation";
import type { BatchListingState } from "./batchDeployState";
import type { PlanDTO } from "../../types";

function stageState(progress: StageProgress): "queued" | "running" | "done" | "failed" {
  if (progress.failed > 0) return "failed";
  if (progress.running > 0) return "running";
  if (progress.total > 0 && progress.completed === progress.total) return "done";
  return "queued";
}

function StageIcon({ state }: { state: ReturnType<typeof stageState> }) {
  if (state === "running") return <span className="dv-spinner" aria-hidden="true" />;
  if (state === "done")
    return (
      <span className="batch-stage__icon" aria-hidden="true">
        ✓
      </span>
    );
  if (state === "failed")
    return (
      <span className="batch-stage__icon" aria-hidden="true">
        !
      </span>
    );
  return (
    <span className="batch-stage__icon" aria-hidden="true">
      ›
    </span>
  );
}

function runningListing(
  stage: string,
  listings: readonly BatchListingState[],
): BatchListingState | undefined {
  return listings.find((listing) => listing.stageRuntime[stage]?.kind === "applying");
}

function exceptionListing(
  stage: string,
  listings: readonly BatchListingState[],
): BatchListingState | undefined {
  return listings.find((listing) => {
    if (listing.stageRuntime[stage]?.kind === "failed") return true;
    if (!listing.stale) return false;
    const plan = listing.plan ?? listing.reviewedPlan;
    return plan?.stage_plans.some(
      (candidate) => candidate.stage === stage && stageWillRun(candidate),
    );
  });
}

function stageWhy(progress: StageProgress, state: ReturnType<typeof stageState>): string {
  if (progress.total === 0) return "No listings will run";
  if (state === "done") return "All listings done";
  return `${progress.total} listing${progress.total === 1 ? "" : "s"} will run`;
}

/** The listing a stage tile points at -- the one running it, else one that
 * needs attention -- or why it points at none. */
function StageFocus({
  running,
  exception,
  why,
  onOpenListing,
}: {
  running: BatchListingState | undefined;
  exception: BatchListingState | undefined;
  why: string;
  onOpenListing: (listing: string) => void;
}) {
  if (running !== undefined) {
    return (
      <button
        type="button"
        className="batch-stage__current"
        onClick={() => onOpenListing(running.listing)}
      >
        Running · {running.listing} →
      </button>
    );
  }
  if (exception !== undefined) {
    return (
      <button
        type="button"
        className="batch-stage__current"
        onClick={() => onOpenListing(exception.listing)}
      >
        Attention · {exception.listing} →
      </button>
    );
  }
  return <div className="dv-step__why">{why}</div>;
}

function AggregateStage({
  stage,
  plans,
  listings,
  onOpenListing,
}: {
  stage: string;
  plans: readonly PlanDTO[];
  listings: readonly BatchListingState[];
  onOpenListing: (listing: string) => void;
}) {
  const progress = aggregateStageProgress(plans, listings, stage);
  const state = stageState(progress);
  const running = runningListing(stage, listings);
  const exception = running === undefined ? exceptionListing(stage, listings) : undefined;
  return (
    <div className={`dv-step batch-stage batch-stage--${state}`}>
      <div className="dv-step__top">
        <StageIcon state={state} />
        <span className="dv-step__name">{STAGE_LABELS[stage] ?? stage}</span>
      </div>
      <div className="batch-stage__count dv-tnum">
        {progress.completed}/{progress.total}
      </div>
      <StageFocus
        running={running}
        exception={exception}
        why={stageWhy(progress, state)}
        onOpenListing={onOpenListing}
      />
    </div>
  );
}

/** Run-level progress. It reads only the PR2 projections, so a stage tile
 * cannot accidentally grow a second definition of runnable or completed. */
export function BatchAggregateStages({
  plans,
  listings,
  onOpenListing,
}: {
  plans: readonly PlanDTO[];
  listings: readonly BatchListingState[];
  onOpenListing: (listing: string) => void;
}) {
  const stages = aggregateStageOrder(plans);

  return (
    <section className="batch-aggregate" aria-labelledby="batch-aggregate-heading">
      <span id="batch-aggregate-heading" className="dv-eyebrow">
        Overall run stages
      </span>
      {stages.length === 0 ? (
        <p className="batch-aggregate__empty">No stages were returned by the plan.</p>
      ) : (
        <div className="dv-steps batch-aggregate__steps">
          {stages.map((stage) => (
            <AggregateStage
              key={stage}
              stage={stage}
              plans={plans}
              listings={listings}
              onOpenListing={onOpenListing}
            />
          ))}
        </div>
      )}
    </section>
  );
}
