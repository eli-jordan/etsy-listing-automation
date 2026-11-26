import { StatusTag } from "../../components/StatusTag";
import { useIsPhone } from "../../phone/usePhone";
import type { ListingStatus } from "../../types";
import type { ControlPhase } from "./deployState";

/**
 * The deploy route's page head: the way back, the title, the listing's
 * status, what the run is doing, and Plan again when a fresh plan is worth
 * offering. On a phone the way back is one back link (phone/base.css draws
 * the chevron) instead of a button and two crumbs.
 */

function metaText(phase: ControlPhase, waitingForBackup: boolean): string {
  switch (phase) {
    case "queued":
      return waitingForBackup ? "Waiting for backup…" : "Waiting for another run…";
    case "planning":
      return "Planning…";
    case "previewing":
      return "Rendering previews…";
    case "ready-work":
    case "ready-blocked":
    case "ready-clean":
      return "Planned just now";
    case "applying":
      return "Applying…";
    case "applied":
      return "Applied just now";
    case "failed":
      return "The plan couldn’t be built. See the message above.";
    case "stale":
      return "This listing changed after it was planned.";
    case "cancelled":
      return "";
  }
}

function BackLinks({
  name,
  backToListings,
  onBack,
}: {
  name: string;
  backToListings: boolean;
  onBack: () => void;
}) {
  const isPhone = useIsPhone();
  if (isPhone) {
    return (
      <button type="button" className="page-head__crumb dv-back-link" onClick={onBack}>
        {backToListings ? "Listings" : name}
      </button>
    );
  }
  return (
    <>
      <button type="button" className="btn btn-secondary dv-back" disabled={false} onClick={onBack}>
        &larr; Back
      </button>
      <span className="page-head__crumb" onClick={onBack}>
        Listings
      </span>
      <span className="page-head__sep">/</span>
      <span className="page-head__crumb" onClick={onBack}>
        {name}
      </span>
      <span className="page-head__sep">/</span>
    </>
  );
}

export function DeployHead({
  name,
  status,
  phase,
  waitingForBackup,
  listingDeleted,
  showPlanAgain,
  onBack,
  onPlanAgain,
}: {
  name: string;
  status: ListingStatus | null;
  phase: ControlPhase;
  waitingForBackup: boolean;
  listingDeleted: boolean;
  showPlanAgain: boolean;
  onBack: () => void;
  onPlanAgain: () => void;
}) {
  return (
    <div className="page-head">
      <BackLinks name={name} backToListings={listingDeleted} onBack={onBack} />
      <h1 className="page-head__title">Deploy</h1>
      {status !== null && <StatusTag status={status} />}
      <span className="page-head__meta">{metaText(phase, waitingForBackup)}</span>
      {showPlanAgain && (
        <div className="page-head__actions dv-head-actions">
          <button
            type="button"
            className={phase === "stale" ? "btn btn-primary" : "btn btn-ghost"}
            onClick={onPlanAgain}
          >
            Plan again
          </button>
        </div>
      )}
    </div>
  );
}
