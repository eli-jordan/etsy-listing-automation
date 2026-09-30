// Shared body of the staging review; `blocked` renders the state where two
// names still need fixing before listings can be created.
import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { CopySimpleIcon } from "@phosphor-icons/react/dist/csr/CopySimple";
import { InfoIcon } from "@phosphor-icons/react/dist/csr/Info";
import { ProhibitIcon } from "@phosphor-icons/react/dist/csr/Prohibit";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import type { ReactNode } from "react";
import { Shell } from "./_Shell";
import { batchLabel, ignoredFiles, stagingRows, type StagingRowFixture } from "./_fixtures";

interface RowView extends StagingRowFixture {
  nameError?: ReactNode;
}

function rowsFor(blocked: boolean): RowView[] {
  if (!blocked) return stagingRows;
  return stagingRows.map((row) => {
    if (row.source === "★★★.png") {
      return {
        ...row,
        name: "",
        nameError: "The file name has no letters or digits. Type a name for this listing.",
      };
    }
    if (row.source === "moss and miles.png") {
      return {
        ...row,
        name: "moss-and-miles",
        kind: "ok",
        nameError: (
          <>
            moss-and-miles is already a listing.{" "}
            <button type="button" className="bc-link" data-goto="batch-create-lofi-v2/staging">
              Use moss-and-miles-2
            </button>
          </>
        ),
      };
    }
    return row;
  });
}

function Check({ row }: { row: RowView }) {
  if (row.kind === "invalid") {
    return (
      <span className="bc-status bc-status--error">
        <ProhibitIcon className="bc-icon" />
        <span>
          <strong>Not created.</strong> <span className="bc-status__text">{row.error}</span>
        </span>
      </span>
    );
  }
  if (row.nameError) {
    return (
      <span className="bc-status bc-status--warn">
        <WarningIcon className="bc-icon" />
        <span className="bc-status__text">{row.nameError}</span>
      </span>
    );
  }
  if (row.kind === "ok") {
    return (
      <span className="bc-status bc-status--ok">
        <CheckCircleIcon className="bc-icon" />
        Ready
      </span>
    );
  }
  return (
    <span className="bc-status bc-status--info">
      {row.kind === "collapsed" ? <CopySimpleIcon className="bc-icon" /> : <InfoIcon className="bc-icon" />}
      <span>
        <span className="bc-status--ok" style={{ fontWeight: 600 }}>
          Ready.
        </span>{" "}
        {row.note}
      </span>
    </span>
  );
}


export function StagingPage({ blocked = false }: { blocked?: boolean }) {
  const rows = rowsFor(blocked);
  const ready = rows.filter((r) => r.kind !== "invalid" && !r.nameError).length;
  const nameProblems = rows.filter((r) => r.nameError).length;
  const invalid = rows.filter((r) => r.kind === "invalid").length;

  return (
    <Shell active="listing-templates">
      <div className="page-head">
        <span className="page-head__crumb" data-goto="batch-create-lofi-v2/templates">
          Listing templates
        </span>
        <span className="page-head__sep">›</span>
        <span className="page-head__crumb" data-goto="batch-create-lofi-v2/new-batch">
          New batch
        </span>
        <span className="page-head__sep">›</span>
        <h1 className="page-head__title">Review 13 designs</h1>
        <div className="page-head__actions">
          <button type="button" className="btn btn-secondary" data-goto="batch-create-lofi-v2/new-batch">
            Cancel staging
          </button>
          {blocked ? (
            <button type="button" className="btn btn-primary" disabled title="Fix 2 names first">
              Create {ready + nameProblems} listings
            </button>
          ) : (
            <button type="button" className="btn btn-primary" data-goto="batch-create-lofi-v2/batch-summary">
              Create {ready} listings
            </button>
          )}
        </div>
      </div>

      <div className="bc-counts">
        <span className="bc-count">
          <span className="bc-dot bc-dot--ok" />
          <strong>{ready}</strong> ready
        </span>
        {nameProblems > 0 && (
          <span className="bc-count">
            <span className="bc-dot bc-dot--warn" />
            <strong>{nameProblems}</strong> names to fix
          </span>
        )}
        <span className="bc-count">
          <span className="bc-dot bc-dot--error" />
          <strong>{invalid}</strong> won't be created
        </span>
        <span className="bc-count">
          <span className="bc-dot" />
          <strong>1</strong> duplicate merged
        </span>
        <details className="bc-disclosure bc-count">
          <summary className="bc-muted">
            <strong>{ignoredFiles.length}</strong> other files ignored ▾
          </summary>
          <span className="bc-mono bc-muted">{ignoredFiles.join(" · ")}</span>
        </details>
      </div>

      <p className="bc-small bc-muted" style={{ margin: "0 0 var(--space-3)" }}>
        Using <strong>heavyweight-tee</strong> as saved at 11:38. Each name becomes both{" "}
        <span className="bc-mono">listings/&lt;name&gt;/</span> and{" "}
        <span className="bc-mono">designs/&lt;name&gt;.png</span>.
      </p>

      <div className="bc-row" style={{ marginBottom: "var(--space-3)" }}>
        <label className="toolbar__filter">
          <span className="toolbar__filter-label">Batch label</span>
          <input className="input" type="text" defaultValue={batchLabel} style={{ width: 300 }} />
        </label>
        <span className="bc-spacer" />
        {blocked ? (
          <span className="bc-status bc-status--warn bc-small">
            <WarningIcon className="bc-icon" />
            <span className="bc-status__text">Fix 2 names to create the listings.</span>
          </span>
        ) : (
          <span className="bc-small bc-muted">
            Each listing is a local draft. Nothing goes to Printify or Etsy.
          </span>
        )}
      </div>

      <table className="bc-table">
        <thead>
          <tr>
            <th style={{ width: "28%" }}>Design</th>
            <th style={{ width: "26%" }}>Listing name</th>
            <th>Check</th>
            <th className="bc-end"> </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.source} className={row.kind === "invalid" ? "bc-tr--muted" : undefined}>
              <td>
                <span className="bc-cell">
                  <span className="listing-thumb listing-thumb--empty" />
                  <span className="bc-cell__text">
                    <span className="bc-cell__sub" style={{ color: "var(--color-text)" }}>
                      {row.source}
                    </span>
                  </span>
                </span>
              </td>
              <td>
                {row.kind === "invalid" ? (
                  <span className="bc-muted bc-small">{row.name}</span>
                ) : (
                  <input
                    className={row.nameError ? "input bc-name-input bc-name-input--invalid" : "input bc-name-input"}
                    type="text"
                    defaultValue={row.name}
                    placeholder="Type a name"
                    aria-invalid={row.nameError ? true : undefined}
                    aria-label={`Listing name for ${row.source}`}
                  />
                )}
              </td>
              <td>
                <Check row={row} />
              </td>
              <td className="bc-end">
                <button type="button" className="bc-quiet" aria-label={`Remove ${row.source}`} title="Remove from batch">
                  <XIcon className="bc-icon" style={{ width: 13, height: 13 }} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className="bc-small bc-muted" style={{ marginTop: "var(--space-3)" }}>
        This staging is saved on the server until 4 Oct, so reloading the page won't lose it. Later
        edits to heavyweight-tee don't change it.
      </p>
    </Shell>
  );
}
