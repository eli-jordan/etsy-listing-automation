import type { ControlPhase } from "./deployState";

/**
 * The bottom of the review: Apply, and a note that always says why it is in
 * whatever state it is in (spec's "Apply footer" element; the control-state
 * table, docs/deploy-changes.md §7's addition).
 */

function note(phase: ControlPhase, previewsTotal: number, previewsDone: number): string {
  switch (phase) {
    case "queued":
      return "Waiting for another run to finish.";
    case "planning":
      return "Apply unlocks once the plan is ready.";
    case "previewing":
      return `Rendering previews (${previewsDone} of ${previewsTotal})…`;
    case "ready-work":
      return "Apply runs exactly this plan. If the listing is saved again before you apply, you’ll be asked to plan again.";
    case "ready-blocked":
      return "Nothing can run until the blocked step is fixed.";
    case "ready-clean":
      return "There is nothing to apply.";
    case "applying":
      return "Running steps in order. You can leave; this keeps going.";
    case "stale":
      return "This listing changed after it was planned. Plan again to review the current version.";
    case "failed":
      return "Apply stopped at a failed step. Plan again to continue.";
    case "cancelled":
      return "This plan was cancelled.";
    case "applied":
      return "";
  }
}

export function ApplyFooter({
  controlPhase,
  previewsTotal,
  previewsDone,
  onApply,
  appliedStepCount,
  backLabel,
  onBack,
}: {
  controlPhase: ControlPhase;
  previewsTotal: number;
  previewsDone: number;
  onApply: () => void;
  /** Only meaningful once `controlPhase === "applied"`. */
  appliedStepCount?: number;
  backLabel?: string;
  onBack?: () => void;
}) {
  if (controlPhase === "applied") {
    const count = appliedStepCount ?? 0;
    return (
      <div className="dv-foot">
        <p>
          Deployed {count} step{count === 1 ? "" : "s"}.
        </p>
        <button type="button" className="btn btn-primary dv-big" onClick={onBack}>
          {backLabel}
        </button>
      </div>
    );
  }

  const applying = controlPhase === "applying";
  const enabled = controlPhase === "ready-work";

  return (
    <div className="dv-foot">
      <p>{note(controlPhase, previewsTotal, previewsDone)}</p>
      <button
        type="button"
        className="btn btn-primary dv-big"
        disabled={!enabled}
        onClick={onApply}
      >
        {applying ? (
          <>
            <span className="dv-spinner" aria-hidden="true" /> Applying&hellip;
          </>
        ) : (
          "Apply"
        )}
      </button>
    </div>
  );
}
