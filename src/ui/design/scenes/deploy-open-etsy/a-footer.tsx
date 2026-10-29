import { ApplyFooter } from "../../../src/pages/deploy/ApplyFooter";
import { DeployResult, OkIcon } from "./_DeployResult";
import { etsyListingId } from "./_fixtures";

export const meta = {
  title: "A · Footer leads to Etsy",
  viewport: "laptop",
  description: "Chosen and built: the applied footer's primary action is Open on Etsy, for drafts and live listings alike; Back to editor is secondary.",
};

export default function Frame() {
  return (
    <DeployResult
      callout={
        <div className="dv-callout dv-callout--ok">
          <OkIcon />
          <div>
            <strong>Deployed.</strong> Printify and Etsy now match this listing, and the plan has
            been used up. Go back to keep editing.
          </div>
        </div>
      }
      footer={
        <ApplyFooter
          controlPhase="applied"
          previewsTotal={0}
          previewsDone={0}
          onApply={() => {}}
          appliedStepCount={6}
          backLabel="← Back to editor"
          etsyListingId={etsyListingId}
        />
      }
    />
  );
}
