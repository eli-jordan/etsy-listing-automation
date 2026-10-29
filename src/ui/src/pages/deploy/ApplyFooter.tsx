import { ArrowSquareOutIcon } from "@phosphor-icons/react/dist/csr/ArrowSquareOut";
import { etsyListingUrl } from "../../components/openOn";
import type { ControlPhase } from "./deployState";

/**
 * The bottom of the review: Apply, and a note that always says why it is in
 * whatever state it is in (spec's "Apply footer" element; the control-state
 * table, docs/features/deploy-20260917/spec.md §7's addition).
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
  etsyListingId,
}: {
  controlPhase: ControlPhase;
  previewsTotal: number;
  previewsDone: number;
  onApply: () => void;
  /** Only meaningful once `controlPhase === "applied"`. */
  appliedStepCount?: number;
  backLabel?: string;
  onBack?: () => void;
  /** The listing's Etsy id after apply, when it has one. A new listing is
   * an Etsy draft the seller still has to publish there, and a live one is
   * worth checking, so either way Etsy is the next step. */
  etsyListingId?: number | null;
}) {
  if (controlPhase === "applied") {
    const count = appliedStepCount ?? 0;
    const onEtsy = etsyListingId !== null && etsyListingId !== undefined;
    return (
      <div className="dv-foot">
        <p>
          Deployed {count} step{count === 1 ? "" : "s"}.
        </p>
        <button
          type="button"
          className={onEtsy ? "btn btn-secondary dv-big" : "btn btn-primary dv-big"}
          onClick={onBack}
        >
          {backLabel}
        </button>
        {onEtsy && (
          <a
            className="btn btn-primary dv-big dv-open-etsy"
            href={etsyListingUrl(etsyListingId)}
            target="_blank"
            rel="noreferrer"
          >
            <span className="row-menu__badge dv-open-etsy__badge" aria-hidden="true">
              E
            </span>
            Open on Etsy
            <ArrowSquareOutIcon className="dv-open-etsy__ext" weight="bold" aria-hidden="true" />
          </a>
        )}
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
