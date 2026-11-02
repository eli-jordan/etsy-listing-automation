import type { BatchResult } from "./batchDeployPresentation";
import {
  resultHeadline,
  resultNeedsAttention,
  resultTone,
  type BatchStage,
} from "./batchDeployView";

function countLabel(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

/** What a finished workspace apply did, listing by listing. */
export function BatchResultCallout({ result }: { result: BatchResult }) {
  return (
    <div
      className={`dv-callout dv-callout--${resultTone(result)}`}
      role={resultNeedsAttention(result) ? "alert" : "status"}
    >
      <strong>{resultHeadline(result)}</strong>
      <p>
        {countLabel(result.succeeded.length, "listing")} succeeded
        {result.failed.length > 0 && ` · ${countLabel(result.failed.length, "listing")} failed`}
        {result.stale.length > 0 && ` · ${countLabel(result.stale.length, "listing")} stale`}
        {result.blocked.length > 0 && ` · ${countLabel(result.blocked.length, "listing")} blocked`}
      </p>
    </div>
  );
}

/** The ready plan's headline counts and how far its previews are. */
export function ReviewSummary({
  affected,
  counts,
  readyPreviews,
  requiredPreviews,
}: {
  affected: number;
  counts: { add: number; edit: number; remove: number };
  readyPreviews: number;
  requiredPreviews: number;
}) {
  return (
    <section className="batch-review-summary" aria-labelledby="batch-review-heading">
      <div>
        <span className="dv-eyebrow">Authoritative review</span>
        <h2 id="batch-review-heading">{affected} affected listings</h2>
        <p>
          {counts.add} to add · {counts.edit} to edit · {counts.remove} to remove
        </p>
      </div>
      <span className="batch-review-summary__previews">
        {requiredPreviews === 0
          ? "All required previews ready"
          : `${readyPreviews} of ${requiredPreviews} previews ready`}
      </span>
    </section>
  );
}

/** The footer's one action: wait, plan again, or apply the reviewed plan. */
export function FooterAction({
  stage,
  planningFailed,
  nothingToDo,
  applyDisabled,
  runnableCount,
  previewsReady,
  onPlanAgain,
  onApply,
}: {
  stage: BatchStage;
  planningFailed: boolean;
  nothingToDo: boolean;
  applyDisabled: boolean;
  runnableCount: number;
  previewsReady: boolean;
  onPlanAgain: () => void;
  onApply: () => void;
}) {
  if (stage === "applying") {
    return (
      <button type="button" className="btn btn-primary dv-big" disabled>
        Applying…
      </button>
    );
  }
  if (planningFailed || nothingToDo || stage === "applied") {
    return (
      <button type="button" className="btn btn-primary dv-big" onClick={onPlanAgain}>
        {planningFailed ? "Try again" : "Plan again"}
      </button>
    );
  }
  const plural = runnableCount === 1 ? "" : "s";
  return (
    <button
      type="button"
      className="btn btn-primary dv-big"
      disabled={applyDisabled}
      onClick={onApply}
      aria-label={`Apply ${runnableCount} listing${plural}`}
      title={
        previewsReady
          ? "Applying reviewed plans is the next step"
          : "Preview images before applying"
      }
    >
      Apply {runnableCount} listing{plural}
    </button>
  );
}
