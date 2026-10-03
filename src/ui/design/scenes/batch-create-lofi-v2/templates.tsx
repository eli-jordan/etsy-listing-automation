// v2 tracks the live app ShellSidebar, StatusTag and AiModeMark; exact state: git
import { CopySimpleIcon } from "@phosphor-icons/react/dist/csr/CopySimple";
import { InfoIcon } from "@phosphor-icons/react/dist/csr/Info";
import { TrashIcon } from "@phosphor-icons/react/dist/csr/Trash";
import { UploadSimpleIcon } from "@phosphor-icons/react/dist/csr/UploadSimple";
import { Shell } from "./_Shell";
import { listingTemplates, recentBatches } from "./_fixtures";

export const meta = {
  title: "Listing templates · v2",
  viewport: "laptop",
  description:
    "Wireframe: listing-template cards (one mid-drag; a drop goes straight to staging) and recent batches, including an unconfirmed staging session.",
};

export default function ListingTemplatesPage() {
  return (
    <Shell active="listing-templates">
      <div className="page-head">
        <h1 className="page-head__title">Listing templates</h1>
        <span className="page-head__meta">3 templates</span>
        <div className="page-head__actions">
          <button type="button" className="btn btn-primary" data-goto="batch-create-lofi-v2/new-batch">
            New batch
          </button>
        </div>
      </div>

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
                {t.batches === 0
                  ? "No batches yet"
                  : `Used by ${t.batches} ${t.batches === 1 ? "batch" : "batches"}`}
              </span>
              <span className="bc-card__drop-hint">Drop PNGs or a ZIP here to start a batch</span>
            </div>
            <div className="bc-card__foot">
              <button type="button" className="btn btn-secondary" data-goto="batch-create-lofi-v2/new-batch">
                Start batch
              </button>
              <button type="button" className="btn btn-ghost" data-goto="batch-create-lofi-v2/template-editor">
                Edit
              </button>
              <span className="bc-spacer" />
              <button
                type="button"
                className="bc-quiet"
                title="Clone listing template"
                aria-label={`Clone ${t.name}`}
                data-goto="batch-create-lofi-v2/template-new"
              >
                <CopySimpleIcon className="bc-icon" style={{ width: 14, height: 14 }} />
              </button>
              <button type="button" className="bc-quiet" title="Delete listing template" aria-label={`Delete ${t.name}`}>
                <TrashIcon className="bc-icon" style={{ width: 14, height: 14 }} />
              </button>
            </div>
            {i === 0 && (
              <div className="bc-card__overlay" data-goto="batch-create-lofi-v2/staging">
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
        <button type="button" className="bc-link" data-goto="batch-create-lofi-v2/template-new">
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
              <th>Status</th>
              <th>Reviewed</th>
              <th className="bc-end"> </th>
            </tr>
          </thead>
          <tbody>
            {recentBatches.map((b) => (
              <tr
                key={b.label}
                className="bc-tr--link"
                data-goto={b.staging ? "batch-create-lofi-v2/staging" : "batch-create-lofi-v2/batch-summary"}
              >
                <td style={{ whiteSpace: "nowrap" }}>
                  <strong>{b.label}</strong>
                </td>
                <td className="bc-muted" style={{ whiteSpace: "nowrap" }}>{b.template}</td>
                <td className="bc-muted" style={{ whiteSpace: "nowrap" }}>{b.created}</td>
                <td className="bc-num">{b.listings ?? "—"}</td>
                <td>
                  {b.staging ? (
                    <span className="bc-status bc-status--warn">
                      <span className="bc-dot bc-dot--warn" style={{ marginTop: 5 }} />
                      <span className="bc-status__text">{b.progress}</span>
                    </span>
                  ) : (
                    b.progress
                  )}
                </td>
                <td className={b.staging ? "bc-muted" : undefined}>{b.reviewed}</td>
                <td className="bc-end">
                  {b.staging && (
                    <button type="button" className="btn btn-secondary" data-goto="batch-create-lofi-v2/staging">
                      Resume staging
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </Shell>
  );
}
