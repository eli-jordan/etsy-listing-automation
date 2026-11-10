import { useState } from "react";
import { Callouts } from "../../../src/pages/deploy/Callouts";
import { buildComparison, type DriftedField } from "../../../src/pages/deploy/comparison";
import { ComparisonView } from "../../../src/pages/deploy/ComparisonView";
import { scrollToDriftRow } from "../../../src/pages/deploy/driftRowAnchor";
import { PageFrame } from "./_DriftPage";
import { builtPlan } from "./_builtPlan";
import { tileFor } from "./_tiles";

export const meta = {
  title: "A · Field lens",
  viewport: "monitor",
  description: "Chosen and built: the real Callouts and ComparisonView, with one drift warning and fields that open in place.",
};

const comparison = buildComparison(builtPlan);

export default function Frame() {
  const [open, setOpen] = useState<string | null>("etsy:description");
  const reveal = (field: DriftedField) => {
    if (field.expandable) setOpen(field.key);
    scrollToDriftRow(field.key);
  };

  return (
    <PageFrame>
      <Callouts plan={builtPlan} comparison={comparison} applied={false} onRevealDrift={reveal} />
      <ComparisonView
        comparison={comparison}
        listing={{ name: "nan-dont-count-on-it", scene: null }}
        renderSnapshot={null}
        previewsRendered={new Set()}
        collapsed={false}
        etsyListingId={builtPlan.etsy_listing_id}
        imageUrlForRef={tileFor}
        openDrift={open}
        onOpenDriftChange={setOpen}
      />
    </PageFrame>
  );
}
