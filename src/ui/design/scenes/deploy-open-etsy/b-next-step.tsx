import { ArrowSquareOutIcon } from "@phosphor-icons/react/dist/csr/ArrowSquareOut";
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { DeployResult, EtsyBadge } from "./_DeployResult";
import { etsyUrl } from "./_fixtures";

export const meta = {
  title: "B · Next-step panel",
  viewport: "laptop",
  description: "The Deployed callout grows into a two-item checklist (done here, left to do on Etsy) with an Etsy-orange button beside it.",
};

export default function Frame() {
  return (
    <DeployResult
      callout={
        <section className="oe-panel" aria-labelledby="oe-panel-title">
          <div>
            <h2 id="oe-panel-title">Deployed. One step left, on Etsy.</h2>
            <ul className="oe-checklist">
              <li className="oe-done">
                <span className="oe-dot oe-dot--done">
                  <CheckIcon size={12} weight="bold" aria-hidden="true" />
                </span>
                Printify and Etsy now match this listing
              </li>
              <li className="oe-todo">
                <span className="oe-dot oe-dot--todo" aria-hidden="true" />
                Review the draft on Etsy and publish it
              </li>
            </ul>
          </div>
          <div className="oe-panel__cta">
            <a className="oe-etsy-solid" href={etsyUrl} target="_blank" rel="noreferrer">
              <EtsyBadge />
              Open draft on Etsy
              <ArrowSquareOutIcon className="oe-ext" weight="bold" aria-hidden="true" />
            </a>
            <span className="oe-panel__sub">
              Opens Shop Manager in a new tab · <a href="#printify">Printify product</a>
            </span>
          </div>
        </section>
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
