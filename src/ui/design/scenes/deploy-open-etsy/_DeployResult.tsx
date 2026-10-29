// The deploy page in its "applied" state, built from the real StepStrip and
// the app's own dv-* classes. Each direction fills three slots: an action in
// the page head, the result callout, and the footer.
import type { ReactNode } from "react";
import { StatusTag } from "../../../src/components/StatusTag";
import { StepStrip } from "../../../src/pages/deploy/StepStrip";
import { listingName, plan, stageRuntime } from "./_fixtures";

export function DeployResult({
  headActions,
  callout,
  footer,
}: {
  headActions?: ReactNode;
  callout: ReactNode;
  footer: ReactNode;
}) {
  return (
    <div className="editor">
      <div className="page-head">
        <button type="button" className="btn btn-secondary dv-back">
          &larr; Back
        </button>
        <span className="page-head__crumb">Listings</span>
        <span className="page-head__sep">/</span>
        <span className="page-head__crumb">{listingName}</span>
        <span className="page-head__sep">/</span>
        <h1 className="page-head__title">Deploy</h1>
        <StatusTag status="deployed" />
        <span className="page-head__meta">Applied just now</span>
        {headActions && <div className="page-head__actions dv-head-actions">{headActions}</div>}
      </div>
      <div className="dv-stack">
        <StepStrip plan={plan} stageRuntime={stageRuntime} heading="What apply did" />
        {callout}
        <details className="dv-approved-comparison">
          <summary>View approved before-and-after comparison</summary>
        </details>
        {footer}
      </div>
    </div>
  );
}

export function OkIcon() {
  return (
    <svg className="dv-callout__icon" viewBox="0 0 20 20" fill="none" stroke="var(--color-accent-2-700)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m5 10.5 3.2 3L15 6.5" />
    </svg>
  );
}

/** Etsy's own mark colour, as the app's Open in menu badge uses it. */
export function EtsyBadge() {
  return <span className="oe-badge" aria-hidden="true">E</span>;
}
