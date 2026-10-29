import { ArrowSquareOutIcon } from "@phosphor-icons/react/dist/csr/ArrowSquareOut";
import { DeployResult, EtsyBadge, OkIcon } from "./_DeployResult";
import { etsyUrl } from "./_fixtures";

export const meta = {
  title: "C · Head button + inline link",
  viewport: "laptop",
  description: "A quiet Open in Etsy button in the page head, where Plan again sits before apply, plus an inline link in the Deployed sentence.",
};

export default function Frame() {
  return (
    <DeployResult
      headActions={
        <a className="btn btn-secondary oe-head-link" href={etsyUrl} target="_blank" rel="noreferrer">
          <EtsyBadge />
          Open in Etsy
          <ArrowSquareOutIcon className="oe-ext" aria-hidden="true" />
        </a>
      }
      callout={
        <div className="dv-callout dv-callout--ok">
          <OkIcon />
          <div>
            <strong>Deployed as a draft.</strong> Printify and Etsy now match this listing. Buyers
            can&rsquo;t see it until you{" "}
            <a className="oe-link" href={etsyUrl} target="_blank" rel="noreferrer">
              publish the draft on Etsy
              <ArrowSquareOutIcon className="oe-ext" weight="bold" aria-hidden="true" />
            </a>
            .
          </div>
        </div>
      }
      footer={
        <div className="dv-foot">
          <p>Deployed 6 steps.</p>
          <button type="button" className="btn btn-primary dv-big">
            &larr; Back to editor
          </button>
        </div>
      }
    />
  );
}
