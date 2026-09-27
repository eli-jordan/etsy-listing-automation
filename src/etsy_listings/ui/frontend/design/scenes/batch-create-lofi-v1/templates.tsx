// v1 tracks the live app ShellSidebar and StatusTag; exact state: git
import { CopySimpleIcon } from "@phosphor-icons/react/dist/csr/CopySimple";
import { InfoIcon } from "@phosphor-icons/react/dist/csr/Info";
import { TrashIcon } from "@phosphor-icons/react/dist/csr/Trash";
import { UploadSimpleIcon } from "@phosphor-icons/react/dist/csr/UploadSimple";
import { Shell } from "./_Shell";
import { listingTemplates, recentBatches } from "./_fixtures";

export const meta = {
  title: "Listing templates · v1",
  viewport: "laptop",
  description:
    "Wireframe: listing-template cards (one shown mid-drag as a drop target) and the recent-batches list.",
};

export default function ListingTemplatesPage() {
  return (
    <Shell active="listing-templates">
      <div className="page-head">
        <h1 className="page-head__title">Listing templates</h1>
        <span className="page-head__meta">3 templates</span>
        <div className="page-head__actions">
          <button type="button" className="btn btn-primary" data-goto="batch-create-lofi-v1/new-batch">
            New batch
          </button>
        </div>
      </div>

      <p className="bc-lede">
        A listing template holds a product's reusable settings: garment, colours, prices, gallery
        and description body. Drop finished PNGs or one ZIP on a template to draft one listing per
        design.
      </p>

      <div className="bc-cards">
        {listingTemplates.map((t, i) => (
          <article key={t.name} className={i === 0 ? "bc-card bc-card--over" : "bc-card"}>
            <div className="bc-card__gallery">
              {t.gallery.slice(0, 3).map((src) => (
                <img key={src} src={src} alt="" />
              ))}
            </div>
            <div className="bc-card__body">
              <span className="bc-card__name">{t.name}</span>
              <span className="bc-card__facts">
                {t.garment} · {t.colours} colours · {t.pricing}
              </span>
              <span className="bc-card__facts">
                {t.gallery.length} gallery images ·{" "}
                {t.batches === 0 ? "No batches yet" : `Used by ${t.batches} ${t.batches === 1 ? "batch" : "batches"}`}
              </span>
              <span className="bc-card__drop-hint">Drop PNGs or a ZIP here to start a batch</span>
            </div>
            <div className="bc-card__foot">
              <button type="button" className="btn btn-secondary" data-goto="batch-create-lofi-v1/new-batch">
                Start batch
              </button>
              <button type="button" className="btn btn-ghost">
                Edit
              </button>
              <span className="bc-spacer" />
              <button type="button" className="bc-quiet" title="Clone listing template">
                <CopySimpleIcon className="bc-icon" style={{ width: 14, height: 14 }} />
              </button>
              <button type="button" className="bc-quiet" title="Delete listing template">
                <TrashIcon className="bc-icon" style={{ width: 14, height: 14 }} />
              </button>
            </div>
            {i === 0 && (
              <div className="bc-card__overlay" data-goto="batch-create-lofi-v1/staging">
                <UploadSimpleIcon className="bc-icon" />
                <strong>Drop to stage 14 PNGs</strong>
                <span className="bc-small">with heavyweight-tee. You review everything before any listing is created.</span>
              </div>
            )}
          </article>
        ))}
      </div>

      <p className="bc-small bc-muted bc-row" style={{ marginTop: "var(--space-3)" }}>
        <InfoIcon className="bc-icon" />
        To make another template, open a finished listing and choose Save as listing template.
        <button type="button" className="bc-link" data-goto="batch-create-lofi-v1/save-template">
          See how
        </button>
      </p>

      <section className="bc-section">
        <h2>Recent batches</h2>
        <table className="bc-table">
          <thead>
            <tr>
              <th>Batch</th>
              <th>Template</th>
              <th>Created</th>
              <th className="bc-num">Listings</th>
              <th>AI drafting</th>
              <th>Reviewed</th>
            </tr>
          </thead>
          <tbody>
            {recentBatches.map((b) => (
              <tr key={b.label} className="bc-tr--link" data-goto="batch-create-lofi-v1/batch-summary">
                <td>
                  <strong>{b.label}</strong>
                </td>
                <td className="bc-muted">{b.template}</td>
                <td className="bc-muted">{b.created}</td>
                <td className="bc-num">{b.listings}</td>
                <td>{b.progress}</td>
                <td>{b.reviewed}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </Shell>
  );
}
