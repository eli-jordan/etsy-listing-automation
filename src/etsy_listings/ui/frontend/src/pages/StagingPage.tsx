import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { CopySimpleIcon } from "@phosphor-icons/react/dist/csr/CopySimple";
import { InfoIcon } from "@phosphor-icons/react/dist/csr/Info";
import { ProhibitIcon } from "@phosphor-icons/react/dist/csr/Prohibit";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { WarningCircleIcon } from "@phosphor-icons/react/dist/csr/WarningCircle";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  cancelStaging,
  confirmStaging,
  getStaging,
  patchStaging,
  stagingThumbnailUrl,
  type StagingDetail,
  type StagingRow,
} from "../api/batches";
import { clock, dayMonth } from "../dates";

/**
 * Staging review (UI doc §5; the `staging` and `staging-blocked` frames): one
 * row per unique design with its source file, an editable listing name and
 * its check. The server works every name out afresh on each answer (A38), so
 * this page only ever sends what the seller typed and draws what comes back.
 *
 * A name problem blocks Create; a design that will not print does not -- it
 * is shown as *Not created* and Create counts only the ready rows. The
 * session lives on the server, so a reload lands here again.
 *
 * A ZIP's files that are not PNGs are only counted, with their names behind
 * the count (spec, *Accepted input*), and a row whose bytes are already in
 * `designs/` says it reuses that file in its note (spec, *Content
 * deduplication*) -- both as the server says them.
 *
 * AI readiness is said only when it fails (`staging.note.md`): a missing
 * prompt, provider or Etsy market access replaces the count strip's right
 * side with a blocking callout, and Create is disabled -- the server refuses
 * the confirm anyway (spec, *Design validation*).
 */

function time(iso: string): string {
  return clock(new Date(iso));
}

function day(iso: string): string {
  return dayMonth(new Date(iso));
}

function Check({ row, onUse }: { row: StagingRow; onUse: (name: string) => void }) {
  if (row.state === "invalid") {
    return (
      <span className="bc-status bc-status--error">
        <ProhibitIcon className="bc-icon" />
        <span>
          <strong>Not created.</strong> <span className="bc-status__text">{row.message}</span>
        </span>
      </span>
    );
  }
  if (row.state === "name") {
    return (
      <span className="bc-status bc-status--warn">
        <WarningIcon className="bc-icon" />
        <span className="bc-status__text">
          {row.message}
          {row.suggestion && (
            <>
              {" "}
              <button
                type="button"
                className="bc-link"
                onClick={() => onUse(row.suggestion as string)}
              >
                Use {row.suggestion}
              </button>
            </>
          )}
        </span>
      </span>
    );
  }
  if (!row.note) {
    return (
      <span className="bc-status bc-status--ok">
        <CheckCircleIcon className="bc-icon" />
        Ready
      </span>
    );
  }
  return (
    <span className="bc-status bc-status--info">
      {row.sources.length > 1 ? (
        <CopySimpleIcon className="bc-icon" />
      ) : (
        <InfoIcon className="bc-icon" />
      )}
      <span>
        <span className="bc-status--ok" style={{ fontWeight: 600 }}>
          Ready.
        </span>{" "}
        {row.note}
      </span>
    </span>
  );
}

/** A name input that sends only what the seller committed: on blur or
 * Enter, and only when it differs from the server's answer. Keyed by that
 * answer, so a new one starts it afresh. */
function NameInput({ row, onCommit }: { row: StagingRow; onCommit: (name: string) => void }) {
  const [value, setValue] = useState(row.name);
  const commit = () => {
    if (value !== row.name) onCommit(value);
  };
  return (
    <input
      className={
        row.state === "name" ? "input bc-name-input bc-name-input--invalid" : "input bc-name-input"
      }
      type="text"
      value={value}
      placeholder="Type a name"
      aria-invalid={row.state === "name" ? true : undefined}
      aria-label={`Listing name for ${row.sources[0]}`}
      onChange={(event) => setValue(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") event.currentTarget.blur();
      }}
    />
  );
}

export function StagingPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [session, setSession] = useState<StagingDetail | null>(null);
  const [label, setLabel] = useState("");
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    let current = true;
    getStaging(id)
      .then((loaded) => {
        if (!current) return;
        setSession(loaded);
        setLabel(loaded.label);
      })
      .catch((exc: Error) => current && setError(exc.message));
    return () => {
      current = false;
    };
  }, [id]);

  function edit(body: Parameters<typeof patchStaging>[1]) {
    patchStaging(id, body)
      .then((next) => {
        setError("");
        setSession(next);
        setLabel(next.label);
      })
      .catch((exc: Error) => setError(exc.message));
  }

  function create() {
    setCreating(true);
    confirmStaging(id)
      .then((batch) => navigate(`/batches/${batch.id}`))
      .catch((exc: Error) => {
        setCreating(false);
        setError(exc.message);
      });
  }

  function cancel() {
    const template = session?.listing_template ?? "";
    cancelStaging(id)
      .then(() => navigate(`/batches/new?template=${encodeURIComponent(template)}`))
      .catch((exc: Error) => setError(exc.message));
  }

  const rows = session?.rows ?? [];
  const ready = rows.filter((row) => row.state === "ready").length;
  const nameProblems = rows.filter((row) => row.state === "name").length;
  const invalid = rows.filter((row) => row.state === "invalid").length;
  const merged = rows.reduce((sum, row) => sum + row.sources.length - 1, 0);
  const ignored = session?.ignored ?? [];
  const fixNames = `Fix ${nameProblems} ${nameProblems === 1 ? "name" : "names"}`;
  const aiBlocked = session?.ai_blocked ?? null;

  return (
    <>
      <div className="page-head">
        <Link className="page-head__crumb" to="/listing-templates">
          Listing templates
        </Link>
        <span className="page-head__sep">/</span>
        <Link
          className="page-head__crumb"
          to={`/batches/new?template=${encodeURIComponent(session?.listing_template ?? "")}`}
        >
          New batch
        </Link>
        <span className="page-head__sep">/</span>
        <h1 className="page-head__title">
          Review {rows.length} {rows.length === 1 ? "design" : "designs"}
        </h1>
        <div className="page-head__actions">
          <button type="button" className="btn btn-secondary" onClick={cancel} disabled={!session}>
            Cancel staging
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!session || nameProblems > 0 || ready === 0 || creating || aiBlocked !== null}
            title={nameProblems > 0 ? `${fixNames} first` : undefined}
            onClick={create}
          >
            Create {ready + nameProblems} {ready + nameProblems === 1 ? "listing" : "listings"}
          </button>
        </div>
      </div>

      {error && (
        <p className="app__status" role="alert">
          {error}
        </p>
      )}

      {session && (
        <>
          <div className="bc-counts">
            <span className="bc-count">
              <span className="bc-dot bc-dot--ok" />
              <strong>{ready}</strong> ready
            </span>
            {nameProblems > 0 && (
              <span className="bc-count">
                <span className="bc-dot bc-dot--warn" />
                <strong>{nameProblems}</strong> {nameProblems === 1 ? "name" : "names"} to fix
              </span>
            )}
            <span className="bc-count">
              <span className="bc-dot bc-dot--error" />
              <strong>{invalid}</strong> won't be created
            </span>
            {merged > 0 && (
              <span className="bc-count">
                <span className="bc-dot" />
                <strong>{merged}</strong> {merged === 1 ? "duplicate" : "duplicates"} merged
              </span>
            )}
            {ignored.length > 0 && (
              <details className="bc-disclosure bc-count">
                <summary className="bc-muted">
                  <strong>{ignored.length}</strong> other {ignored.length === 1 ? "file" : "files"}{" "}
                  ignored ▾
                </summary>
                <span className="bc-mono bc-muted">{ignored.join(" · ")}</span>
              </details>
            )}
            {aiBlocked && (
              <>
                <span className="bc-spacer" />
                <div className="dv-callout dv-callout--blocked bc-ai-blocked" role="alert">
                  <WarningCircleIcon className="dv-callout__icon" />
                  <div>
                    <strong>AI drafting can't run yet.</strong> {aiBlocked.message}{" "}
                    {aiBlocked.remedy}
                  </div>
                </div>
              </>
            )}
          </div>

          <p className="bc-small bc-muted" style={{ margin: "0 0 var(--space-3)" }}>
            Using <strong>{session.listing_template}</strong> as saved at{" "}
            {time(session.template_saved_at)}. Each name becomes both{" "}
            <span className="bc-mono">listings/&lt;name&gt;/</span> and{" "}
            <span className="bc-mono">designs/&lt;name&gt;.png</span>.
          </p>

          <div className="bc-row" style={{ marginBottom: "var(--space-3)" }}>
            <label className="toolbar__filter">
              <span className="toolbar__filter-label">Batch label</span>
              <input
                className="input"
                type="text"
                value={label}
                style={{ width: 300 }}
                onChange={(event) => setLabel(event.target.value)}
                onBlur={() => label !== session.label && edit({ label })}
                onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()}
              />
            </label>
            <span className="bc-spacer" />
            {nameProblems > 0 ? (
              <span className="bc-status bc-status--warn bc-small">
                <WarningIcon className="bc-icon" />
                <span className="bc-status__text">{fixNames} to create the listings.</span>
              </span>
            ) : (
              <span className="bc-small bc-muted">
                Each listing is a local draft. Nothing goes to Printify or Etsy.
              </span>
            )}
          </div>

          <table className="listings bc-table">
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
                <tr key={row.id} className={row.state === "invalid" ? "bc-tr--muted" : undefined}>
                  <td>
                    <span className="bc-cell">
                      <img className="listing-thumb" src={stagingThumbnailUrl(id, row.id)} alt="" />
                      <span className="bc-cell__text">
                        <span className="bc-cell__sub" style={{ color: "var(--color-text)" }}>
                          {row.sources[0]}
                        </span>
                      </span>
                    </span>
                  </td>
                  <td>
                    {row.state === "invalid" ? (
                      <span className="bc-muted bc-small">{row.name}</span>
                    ) : (
                      <NameInput
                        key={row.name}
                        row={row}
                        onCommit={(name) => edit({ names: { [row.id]: name } })}
                      />
                    )}
                  </td>
                  <td>
                    <Check row={row} onUse={(name) => edit({ names: { [row.id]: name } })} />
                  </td>
                  <td className="bc-end">
                    <button
                      type="button"
                      className="bc-quiet"
                      aria-label={`Remove ${row.sources[0]}`}
                      title="Remove from batch"
                      onClick={() => edit({ remove: [row.id] })}
                    >
                      <XIcon className="bc-icon" style={{ width: 13, height: 13 }} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <p className="bc-small bc-muted" style={{ marginTop: "var(--space-3)" }}>
            This staging is saved on the server until {day(session.expires_at)}, so reloading the
            page won't lose it. Later edits to {session.listing_template} don't change it.
          </p>
        </>
      )}
    </>
  );
}
