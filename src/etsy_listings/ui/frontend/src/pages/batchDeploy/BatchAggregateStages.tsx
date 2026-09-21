import { STAGE_LABELS } from "../../types";
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
    return plan?.stage_plans.some((candidate) => candidate.stage === stage && candidate.will_run);
  });
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
          {stages.map((stage) => {
            const progress = aggregateStageProgress(plans, listings, stage);
            const state = stageState(progress);
            const running = runningListing(stage, listings);
            const exception = running === undefined ? exceptionListing(stage, listings) : undefined;
            const label = STAGE_LABELS[stage] ?? stage;
            return (
              <div key={stage} className={`dv-step batch-stage batch-stage--${state}`}>
                <div className="dv-step__top">
                  <StageIcon state={state} />
                  <span className="dv-step__name">{label}</span>
                </div>
                <div className="batch-stage__count dv-tnum">
                  {progress.completed}/{progress.total}
                </div>
                {running !== undefined ? (
                  <button
                    type="button"
                    className="batch-stage__current"
                    onClick={() => onOpenListing(running.listing)}
                  >
                    Running · {running.listing} →
                  </button>
                ) : exception !== undefined ? (
                  <button
                    type="button"
                    className="batch-stage__current"
                    onClick={() => onOpenListing(exception.listing)}
                  >
                    Attention · {exception.listing} →
                  </button>
                ) : (
                  <div className="dv-step__why">
                    {progress.total === 0
                      ? "No listings will run"
                      : state === "done"
                        ? "All listings done"
                        : `${progress.total} listing${progress.total === 1 ? "" : "s"} will run`}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
