import { AiWorkflowIndicator, type WorkflowStep } from "../../screens/marketSeo/AiWorkflowIndicator";
import { MarketListingsPanel } from "../../screens/marketSeo/MarketListingsPanel";
import "../../screens/marketSeo/marketSeo.css";
import { queries, research, steps } from "./_fixtures";

export const meta = {
  title: "Market SEO — workflow and panel states",
  viewport: "laptop",
  description: "Every state of the workflow indicator (with hover cards pinned open) and the panel's phrases, empty and failed states.",
};

const rows: { label: string; steps: WorkflowStep[]; tip?: "brief" | "market" | "seo" }[] = [
  { label: "Drafting the brief", steps: steps.briefActive, tip: "brief" },
  { label: "Researching the market", steps: steps.researching, tip: "market" },
  { label: "Seller wrote the brief", steps: steps.briefSkipped, tip: "brief" },
  { label: "Writing suggestions", steps: steps.suggesting, tip: "seo" },
  { label: "No comparable listings", steps: steps.noComparables, tip: "market" },
  { label: "Market search failed", steps: steps.marketFailed, tip: "market" },
  { label: "Done (fades after a few seconds)", steps: steps.ready },
];

export default function States() {
  return (
    <div className="mkt-states">
      <section>
        <h2>Workflow indicator</h2>
        <div className="mkt-states__grid">
          {rows.map((row) => (
            <div className="mkt-states__cell" key={row.label}>
              <span className="mkt-states__label">{row.label}</span>
              <AiWorkflowIndicator steps={row.steps} openTip={row.tip} />
            </div>
          ))}
        </div>
      </section>
      <section>
        <h2>Top listings panel</h2>
        <div className="mkt-states__panels">
          <div><span className="mkt-states__label">Phrases view</span><MarketListingsPanel state={{ kind: "ready", research }} initialView="phrases" /></div>
          <div><span className="mkt-states__label">Nothing comparable</span><MarketListingsPanel state={{ kind: "empty", queries }} /></div>
          <div><span className="mkt-states__label">Search failed</span><MarketListingsPanel state={{ kind: "failed", reason: "Etsy did not respond (HTTP 503) after 3 retries." }} /></div>
        </div>
      </section>
    </div>
  );
}
