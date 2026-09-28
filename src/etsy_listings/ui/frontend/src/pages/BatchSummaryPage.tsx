import { ArrowClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowClockwise";
import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { ClockIcon } from "@phosphor-icons/react/dist/csr/Clock";
import { MinusCircleIcon } from "@phosphor-icons/react/dist/csr/MinusCircle";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { WarningCircleIcon } from "@phosphor-icons/react/dist/csr/WarningCircle";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  controlBatch,
  getBatch,
  retryBatchRow,
  type BatchDetail,
  type BatchRow,
} from "../api/batches";
import { listingDesignThumbnailUrl } from "../api/listings";
import { AiWorkflowIndicator } from "./editor/aiSeo/AiWorkflowIndicator";

/**
 * The batch summary (UI doc §7; the `batch-summary` frame): the batch's one
 * review surface. A progress bar and a count strip sit above one row per
 * listing, with its AI drafting and its SEO proposal, and the queue's
 * controls -- Cancel batch, Resume, Retry N failed (A40).
 *
 * Running and failed rows mount the editor's own step indicator, so a batch
 * row and an open editor read the same way; a finished row says *done*
 * instead, as the editor hides the indicator once a run completes. The
 * queue runs on the server whether this tab is open or not, so the page
 * only polls while a row is queued or running.
 *
 * Reviewed, renaming the label and deleting the record come with review
 * (batch plan PR 5).
 */

export const POLL_MS = 2000;

const ORDINAL = ["", "next", "2nd", "3rd"];

function place(position: number): string {
  return ORDINAL[position] ?? `${position}th`;
}

function createdAt(iso: string): string {
  const created = new Date(iso);
  const time = created.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  const today = created.toDateString() === new Date().toDateString();
  const day = today
    ? "today"
    : `on ${created.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}`;
  return `${day} at ${time}`;
}

type Kind = "drafted" | "drafting" | "queued" | "retry" | "stopped" | "none";

function kindOf(row: BatchRow): Kind {
  if (row.creation === "failed") return "retry";
  if (row.creation !== "created") return "none";
  switch (row.ai) {
    case "done":
      return "drafted";
    case "running":
      return "drafting";
    case "queued":
      return "queued";
    case "failed":
      return "retry";
    case "stopped":
    case "cancelled":
      return "stopped";
    default:
      return "none";
  }
}

/** Retry reruns only what failed: a row that has its brief keeps it. */
function failure(row: BatchRow): string {
  const message = (row.ai_error ?? "The AI run failed").replace(/\.?$/, ".");
  const brief = row.ai_steps.find((step) => step.id === "brief");
  const kept = brief?.state === "done" || brief?.state === "skipped";
  return kept ? `${message} The brief is saved; Retry reruns research and SEO.` : message;
}

function AiCell({ row }: { row: BatchRow }) {
  if (row.creation === "failed") {
    return (
      <span className="bc-status bc-status--error">
        <WarningCircleIcon className="bc-icon" />
        <span className="bc-status__text">{row.error}</span>
      </span>
    );
  }
  if (row.creation !== "created") {
    return (
      <span className="bc-status bc-status--info">
        <ClockIcon className="bc-icon" />
        Not created yet
      </span>
    );
  }
  switch (row.ai) {
    case "done":
      return (
        <span className="bc-status bc-status--ok">
          <CheckCircleIcon className="bc-icon" />
          Brief, market research and SEO done
        </span>
      );
    case "running":
      return row.ai_steps.length > 0 ? (
        <AiWorkflowIndicator steps={row.ai_steps} running />
      ) : (
        <span className="bc-status bc-status--info">
          <ClockIcon className="bc-icon" />
          Starting…
        </span>
      );
    case "queued":
      return (
        <span className="bc-status bc-status--info">
          <ClockIcon className="bc-icon" />
          Queued, {place(row.queue_position ?? 1)} in line
        </span>
      );
    case "failed":
      return (
        <span className="bc-cell__text bc-aiflow-cell" style={{ gap: 4 }}>
          <AiWorkflowIndicator steps={row.ai_steps} running={false} />
          <span className="bc-status bc-status--error">
            <span className="bc-status__text">{failure(row)}</span>
          </span>
        </span>
      );
    case "stopped":
    case "cancelled":
      return (
        <span className="bc-status bc-status--info">
          <MinusCircleIcon className="bc-icon" />
          Stopped. Resume queues it again.
        </span>
      );
    default:
      return <span className="bc-muted">—</span>;
  }
}

function ProposalCell({ row }: { row: BatchRow }) {
  if (row.proposal === "ready") return <span className="tag tag-accent">Ready to review</span>;
  if (row.proposal === "stale") {
    return (
      <span className="bc-status bc-status--warn">
        <WarningIcon className="bc-icon" />
        <span className="bc-status__text">Stale: {row.stale_reasons.join(", ")}</span>
      </span>
    );
  }
  if (row.proposal === "resolved") return <span className="bc-muted">Suggestions used</span>;
  return <span className="bc-muted">—</span>;
}

export function BatchSummaryPage() {
  const { id = "" } = useParams();
  const [batch, setBatch] = useState<BatchDetail | null>(null);
  const [error, setError] = useState("");

  const rows = batch?.rows ?? [];
  const kinds = rows.map(kindOf);
  const count = (kind: Kind) => kinds.filter((k) => k === kind).length;
  const busy = count("drafting") + count("queued") > 0;

  // The first load, then one every POLL_MS for as long as a row is queued
  // or running.
  useEffect(() => {
    let current = true;
    const load = () =>
      getBatch(id)
        .then((loaded) => current && setBatch(loaded))
        .catch((exc: Error) => current && setError(exc.message));
    void load();
    return () => {
      current = false;
    };
  }, [id]);
  useEffect(() => {
    if (!busy) return;
    let current = true;
    const timer = setInterval(() => {
      getBatch(id)
        .then((loaded) => current && setBatch(loaded))
        .catch(() => {});
    }, POLL_MS);
    return () => {
      current = false;
      clearInterval(timer);
    };
  }, [id, busy]);

  function act(request: Promise<BatchDetail>) {
    request
      .then((next) => {
        setError("");
        setBatch(next);
      })
      .catch((exc: Error) => setError(exc.message));
  }

  const total = rows.length || 1;
  const segments: [number, string][] = [
    [count("drafted"), "var(--color-accent-2)"],
    [count("drafting"), "var(--color-accent)"],
    [count("queued"), "var(--color-neutral-500)"],
    [count("retry"), "var(--color-danger)"],
  ];
  const needRetry = count("retry");
  const concurrency = batch?.concurrency ?? 1;
  const pace =
    concurrency === 1
      ? "Drafting one listing at a time."
      : `Drafting up to ${concurrency} listings at a time.`;

  return (
    <>
      <div className="page-head">
        <Link className="page-head__crumb" to="/listing-templates">
          Listing templates
        </Link>
        <span className="page-head__sep">/</span>
        <h1 className="page-head__title">{batch?.label ?? "Batch"}</h1>
        <div className="page-head__actions">
          {busy ? (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => act(controlBatch(id, "cancel"))}
            >
              Cancel batch
            </button>
          ) : (
            count("stopped") > 0 && (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => act(controlBatch(id, "resume"))}
              >
                Resume
              </button>
            )
          )}
        </div>
      </div>

      {error && (
        <p className="app__status" role="alert">
          {error}
        </p>
      )}

      {batch && (
        <>
          <div className="bc-progress" aria-hidden="true">
            {segments.map(([n, color]) => (
              <span key={color} style={{ width: `${(n / total) * 100}%`, background: color }} />
            ))}
          </div>

          <div className="bc-counts">
            <span className="bc-count">
              <span className="bc-dot bc-dot--ok" />
              <strong>{count("drafted")}</strong> drafted
            </span>
            <span className="bc-count">
              <span className="bc-dot bc-dot--busy" />
              <strong>{count("drafting")}</strong> drafting
            </span>
            <span className="bc-count">
              <span className="bc-dot" />
              <strong>{count("queued")}</strong> queued
            </span>
            <span className="bc-count">
              <span className="bc-dot bc-dot--error" />
              <strong>{needRetry}</strong> need retry
            </span>
            {count("stopped") > 0 && (
              <span className="bc-count bc-muted">
                <strong>{count("stopped")}</strong> stopped
              </span>
            )}
            <span className="bc-spacer" />
            {needRetry > 0 && (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => act(controlBatch(id, "retry"))}
              >
                <ArrowClockwiseIcon
                  className="bc-icon"
                  style={{ verticalAlign: -3, marginRight: 6 }}
                />
                Retry {needRetry} failed
              </button>
            )}
          </div>

          <p className="bc-small bc-muted" style={{ margin: "0 0 var(--space-3)" }}>
            Created {createdAt(batch.created_at)} from {batch.listing_template}. {pace} Work carries
            on if you close this tab. Briefs are written for you; titles, tags and the description
            lead wait for you to accept them in each listing.
          </p>

          <table className="listings bc-table">
            <thead>
              <tr>
                <th style={{ width: "22%" }}>Listing</th>
                <th>AI drafting</th>
                <th style={{ width: "17%" }}>SEO proposal</th>
                <th className="bc-end"> </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => {
                const exists = row.creation === "created";
                const retryable = kinds[index] === "retry";
                return (
                  <tr key={row.id} className={exists ? undefined : "bc-tr--muted"}>
                    <td>
                      <span className="bc-cell">
                        {exists && (
                          <img
                            className="listing-thumb"
                            src={listingDesignThumbnailUrl(row.design)}
                            alt=""
                          />
                        )}
                        {exists ? (
                          <Link className="listing-row__link" to={`/listings/${row.name}`}>
                            {row.name}
                          </Link>
                        ) : (
                          <span style={{ fontWeight: 600 }}>{row.name}</span>
                        )}
                      </span>
                    </td>
                    <td>
                      <AiCell row={row} />
                    </td>
                    <td>
                      <ProposalCell row={row} />
                    </td>
                    <td className="bc-end">
                      {retryable && (
                        <button
                          type="button"
                          className="btn btn-ghost"
                          onClick={() => act(retryBatchRow(id, row.id))}
                        >
                          Retry
                        </button>
                      )}
                      {exists && (
                        <Link className="btn btn-ghost" to={`/listings/${row.name}`}>
                          Open
                        </Link>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}
    </>
  );
}
