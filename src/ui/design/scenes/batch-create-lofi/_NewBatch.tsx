// Shared body of the New batch page; `refused` renders the upload-refused state.
import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { FileZipIcon } from "@phosphor-icons/react/dist/csr/FileZip";
import { WarningCircleIcon } from "@phosphor-icons/react/dist/csr/WarningCircle";
import { Shell } from "./_Shell";
import { listingTemplates } from "./_fixtures";

export function NewBatchPage({ refused = false }: { refused?: boolean }) {
  return (
    <Shell active="listing-templates">
      <div className="page-head">
        <span className="page-head__crumb" data-goto="batch-create-lofi/templates">
          Listing templates
        </span>
        <span className="page-head__sep">/</span>
        <h1 className="page-head__title">New batch</h1>
      </div>

      <div className="bc-steps">
        <section className="bc-step">
          <h2>1. Listing template</h2>
          <p className="bc-muted bc-small">Every design in this batch gets the same product settings.</p>
          <div className="bc-picks" role="radiogroup" aria-label="Listing template">
            {listingTemplates.map((t, i) => (
              <button
                key={t.name}
                type="button"
                role="radio"
                aria-checked={i === 0}
                className={i === 0 ? "bc-pick bc-pick--on" : "bc-pick"}
              >
                <img src={t.gallery[0]} alt="" />
                <span className="bc-cell__text">
                  <span className="bc-pick__name">{t.name}</span>
                  <span className="bc-pick__facts">
                    {t.garment} · {t.colours} colours
                  </span>
                </span>
              </button>
            ))}
          </div>
        </section>

        <section className="bc-step">
          <h2>2. Designs</h2>
          <p className="bc-muted bc-small">
            One ZIP, or any number of loose PNGs. Up to 25 designs per batch.
          </p>

          {refused && (
            <div className="dv-callout dv-callout--blocked" style={{ marginBottom: "var(--space-3)" }} role="alert">
              <WarningCircleIcon className="dv-callout__icon" />
              <div>
                <strong>kittl-export-autumn.zip was not staged.</strong>
                <div>It holds 31 different PNG designs, and a batch takes at most 25.</div>
                <div className="dv-callout__remedy">
                  Split the export into two ZIPs and start a batch for each. Nothing was uploaded
                  or changed.
                </div>
              </div>
            </div>
          )}

          <div
            className={refused ? "bc-drop bc-drop--error" : "bc-drop"}
            role="button"
            tabIndex={0}
            data-goto="batch-create-lofi/staging"
          >
            <FileZipIcon className="bc-drop__icon" />
            <span className="bc-drop__title">
              {refused ? "Drop a different ZIP or PNGs" : "Drop a ZIP or PNGs here"}
            </span>
            <span className="bc-small bc-muted">
              Kittl exports work as they are. Every PNG in the ZIP, in any folder, becomes a design.
            </span>
            <span className="bc-row" style={{ marginTop: "var(--space-1)" }}>
              <button type="button" className="btn btn-secondary" data-goto="batch-create-lofi/staging">
                Choose files…
              </button>
            </span>
          </div>

          <div className="bc-reqs">
            <span className="bc-req">
              <CheckCircleIcon className="bc-icon" />
              PNG with a transparent background
            </span>
            <span className="bc-req">
              <CheckCircleIcon className="bc-icon" />
              At least 3402 × 4050 px (90% of the Comfort Colors 1717 print area)
            </span>
            <span className="bc-req">
              <CheckCircleIcon className="bc-icon" />
              Not both a ZIP and loose PNGs, and never more than one ZIP
            </span>
          </div>

          {!refused && (
            <p className="bc-small bc-muted" style={{ marginTop: "var(--space-3)" }}>
              Wrong file?{" "}
              <button type="button" className="bc-link" data-goto="batch-create-lofi/staging-refused">
                See what a refused upload looks like
              </button>
            </p>
          )}
        </section>
      </div>
    </Shell>
  );
}
