// v3 tracks the live app ShellSidebar, StatusTag and AiModeMark; exact state: git
import { CopySimpleIcon } from "@phosphor-icons/react/dist/csr/CopySimple";
import { InfoIcon } from "@phosphor-icons/react/dist/csr/Info";
import { TrashIcon } from "@phosphor-icons/react/dist/csr/Trash";
import { UploadSimpleIcon } from "@phosphor-icons/react/dist/csr/UploadSimple";
import { Shell } from "./_Shell";
import { listingTemplates, recentBatches, type BatchStatus } from "./_fixtures";

const STATUS: Record<BatchStatus, { label: string; className: string }> = {
  staging: { label: "Staging", className: "tag tag-neutral" },
  drafting: { label: "Drafting", className: "tag tag-accent" },
  "in-review": { label: "In review", className: "tag tag-accent" },
  complete: { label: "Complete", className: "tag tag-accent-2" },
  stopped: { label: "Stopped", className: "tag tag-neutral" },
};

function BatchStatusTag({ status }: { status: BatchStatus }) {
  const s = STATUS[status];
  return (
    <span className={s.className} style={{ gap: 5 }}>
      {status === "drafting" && <span className="dv-spinner" style={{ width: 9, height: 9, borderWidth: 1.5 }} />}
      {s.label}
    </span>
  );
}

export const meta = {
  title: "Listing templates · v3",
  viewport: "laptop",
  description:
    "Wireframe: listing-template cards (one mid-drag; a drop goes straight to staging) and recent batches with a lifecycle status per batch.",
};

export default function ListingTemplatesPage() {
  return (
    <Shell active="listing-templates">
      <div className="page-head">
        <h1 className="page-head__title">Listing templates</h1>
        <span className="page-head__meta">3 templates</span>
        <div className="page-head__actions">
          <button type="button" className="btn btn-primary" data-goto="batch-create-lofi-v3/new-batch">
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
              <button type="button" className="btn btn-secondary" data-goto="batch-create-lofi-v3/new-batch">
                Start batch
              </button>
              <button type="button" className="btn btn-ghost" data-goto="batch-create-lofi-v3/template-variants">
                Edit
              </button>
              <span className="bc-spacer" />
              <button
                type="button"
                className="bc-quiet"
                title="Clone listing template"
                aria-label={`Clone ${t.name}`}
                data-goto="batch-create-lofi-v3/template-new"
              >
                <CopySimpleIcon className="bc-icon" style={{ width: 14, height: 14 }} />
              </button>
              <button type="button" className="bc-quiet" title="Delete listing template" aria-label={`Delete ${t.name}`}>
                <TrashIcon className="bc-icon" style={{ width: 14, height: 14 }} />
              </button>
            </div>
            {i === 0 && (
              <div className="bc-card__overlay" data-goto="batch-create-lofi-v3/staging">
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
        <button type="button" className="bc-link" data-goto="batch-create-lofi-v3/template-new">
          See how
        </button>
      </p>

      <section className="bc-section">
        <h2>Recent batches</h2>
        <table className="bc-table">
          <thead>
            <tr>
              <th>Batch</th>
              <th>Status</th>
              <th>Progress</th>
              <th>Template</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {recentBatches.map((b) => {
              const goto =
                b.status === "staging" ? "batch-create-lofi-v3/staging" : "batch-create-lofi-v3/batch-summary";
              return (
                <tr key={b.label} className="bc-tr--link" data-goto={goto}>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button type="button" className="listing-row__link" data-goto={goto}>
                      {b.label}
                    </button>
                  </td>
                  <td>
                    <BatchStatusTag status={b.status} />
                  </td>
                  <td>
                    {b.progress}
                    {b.attention && (
                      <span className="bc-status bc-status--error" style={{ marginLeft: 8 }}>
                        <span className="bc-dot bc-dot--error" style={{ marginTop: 5 }} />
                        {b.attention}
                      </span>
                    )}
                  </td>
                  <td className="bc-muted" style={{ whiteSpace: "nowrap" }}>
                    {b.template}
                  </td>
                  <td className="bc-muted" style={{ whiteSpace: "nowrap" }}>
                    {b.created}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </Shell>
  );
}
