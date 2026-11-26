import { ArrowClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowClockwise";
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { ClockIcon } from "@phosphor-icons/react/dist/csr/Clock";
import { MinusCircleIcon } from "@phosphor-icons/react/dist/csr/MinusCircle";
import { TrashIcon } from "@phosphor-icons/react/dist/csr/Trash";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { WarningCircleIcon } from "@phosphor-icons/react/dist/csr/WarningCircle";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  batchRowThumbnailUrl,
  controlBatch,
  deleteBatch,
  getBatch,
  renameBatch,
  retryBatchRow,
  setReviewed,
  type BatchDetail,
  type BatchRow,
} from "../api/batches";
import { listingDesignThumbnailUrl, listListings } from "../api/listings";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { ListingHover } from "../components/ListingHover";
import type { ListingSummary } from "../types";
import { clock, dayMonth } from "../dates";
import { EditableName } from "../components/EditableName";
import { useIsPhone } from "../phone/usePhone";
import { AiWorkflowIndicator } from "./editor/aiSeo/AiWorkflowIndicator";
import { BatchDeployReviewedButton } from "./batchDeploy/BatchDeployReviewedButton";

export const POLL_MS = 2000;

const ORDINAL = ["", "next", "2nd", "3rd"];

function place(position: number): string {
  return ORDINAL[position] ?? `${position}th`;
}

function createdAt(iso: string): string {
  const created = new Date(iso);
  const today = created.toDateString() === new Date().toDateString();
  const day = today ? "today" : `on ${dayMonth(created)}`;
  return `${day} at ${clock(created)}`;
}

type Kind =
  "drafted" | "drafting" | "queued" | "retry" | "stopped" | "deployed" | "deleted" | "none";

function kindOf(row: BatchRow): Kind {
  if (row.deleted) return "deleted";
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
    case "cancelled_by_deploy":
      return "deployed";
    default:
      return "none";
  }
}

function failure(row: BatchRow): string {
  const message = (row.ai_error ?? "The AI run failed").replace(/\.?$/, ".");
  const brief = row.ai_steps.find((step) => step.id === "brief");
  const kept = brief?.state === "done" || brief?.state === "skipped";
  return kept
    ? `${message} The brief is saved. Retry keeps it. Start AI Mode in the listing for research and SEO.`
    : message;
}

function AiCell({ row }: { row: BatchRow }) {
  if (row.deleted) {
    return (
      <span className="bc-status bc-status--info">
        <MinusCircleIcon className="bc-icon" />
        Listing deleted. Its AI work was cancelled.
      </span>
    );
  }
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
          Brief ready
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
          {row.waiting_for_backup
            ? "Queued, waiting for backup"
            : `Queued, ${place(row.queue_position ?? 1)} in line`}
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
    case "cancelled_by_deploy":
      return (
        <span className="bc-status bc-status--info">
          <MinusCircleIcon className="bc-icon" />
          Cancelled for deploy. Retry drafts it again.
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
  if (!row.deleted && row.creation === "created" && row.ai === "done") {
    return <span className="bc-muted">Start AI Mode in the listing</span>;
  }
  return <span className="bc-muted">—</span>;
}

const DELETE_DETAILS =
  "Deleting the batch record keeps every listing, design, brief and proposal it made. Its queued and running AI work is cancelled first, and its review flags go with the record.";

function ReviewedCell({ row, onReview }: { row: BatchRow; onReview: (next: boolean) => void }) {
  if (!row.reviewable) return <span className="bc-muted">—</span>;
  if (row.reviewed) {
    return (
      <button
        type="button"
        className="bc-quiet bc-quiet--on"
        title="Mark needs review"
        onClick={() => onReview(false)}
      >
        <CheckIcon
          className="bc-icon"
          style={{ width: 12, height: 12, verticalAlign: -2, marginRight: 4 }}
        />
        Reviewed
      </button>
    );
  }
  return (
    <button type="button" className="bc-quiet" onClick={() => onReview(true)}>
      Mark reviewed
    </button>
  );
}

/** The phone card's Reviewed: a labelled switch, since the desktop's
 * "✓ Reviewed" reads as a status and only a hover title says a click
 * clears it. */
function ReviewedSwitch({ row, onReview }: { row: BatchRow; onReview: (next: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={row.reviewed}
      className="m-switch"
      onClick={() => onReview(!row.reviewed)}
    >
      <span className="m-switch__track" aria-hidden="true">
        <span className="m-switch__thumb" />
      </span>
      <span className="m-switch__label">Reviewed</span>
    </button>
  );
}

/** The Listings table's summary of each of the batch's listings, for the
 * name's hover card (the same one the Listings page shows). Asked once per
 * set of names, not on every poll: a row's name changes only when it is
 * created, renamed or deleted, and the card is extra -- if the summaries
 * will not load, the names are plain links. */
function useListingSummaries(names: string[]): Map<string, ListingSummary> {
  const [summaries, setSummaries] = useState<Map<string, ListingSummary>>(new Map());
  const key = [...names].sort().join("\n");
  useEffect(() => {
    if (key === "") return;
    let current = true;
    listListings()
      .then((all) => {
        if (current) setSummaries(new Map(all.map((summary) => [summary.name, summary])));
      })
      .catch(() => {});
    return () => {
      current = false;
    };
  }, [key]);
  return summaries;
}

function editorUrl(batch: string, row: BatchRow): string {
  return `/listings/${encodeURIComponent(row.name)}?batch=${encodeURIComponent(batch)}`;
}

function PhoneRowCard({
  batch,
  row,
  retryable,
  onReview,
  onRetry,
}: {
  batch: string;
  row: BatchRow;
  retryable: boolean;
  onReview: (next: boolean) => void;
  onRetry: () => void;
}) {
  const open = row.creation === "created" && !row.deleted;
  const thumb = (
    <img
      className="listing-thumb"
      src={
        row.creation === "created"
          ? listingDesignThumbnailUrl(row.design)
          : batchRowThumbnailUrl(batch, row.id)
      }
      alt=""
    />
  );
  const name = row.deleted ? <s>{row.name}</s> : row.name;
  return (
    <li className={open ? "m-card" : "m-card m-card--muted"}>
      {open ? (
        <Link className="m-card__head" to={editorUrl(batch, row)}>
          {thumb}
          <span className="m-row__name">{name}</span>
          <span className="m-chevron" aria-hidden="true" />
        </Link>
      ) : (
        <span className="m-card__head">
          {thumb}
          <span className="m-row__name">{name}</span>
        </span>
      )}
      <dl className="m-card__facts">
        <dt>AI drafting</dt>
        <dd>
          <AiCell row={row} />
        </dd>
        <dt>SEO proposal</dt>
        <dd>
          <ProposalCell row={row} />
        </dd>
      </dl>
      {(row.reviewable || retryable) && (
        <div className="m-card__actions">
          {row.reviewable && <ReviewedSwitch row={row} onReview={onReview} />}
          {retryable && (
            <button type="button" className="btn btn-secondary" onClick={onRetry}>
              Retry
            </button>
          )}
        </div>
      )}
    </li>
  );
}

export function BatchSummaryPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [batch, setBatch] = useState<BatchDetail | null>(null);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState(false);
  const isPhone = useIsPhone();

  const rows = batch?.rows ?? [];
  const kinds = rows.map(kindOf);
  const count = (kind: Kind) => kinds.filter((k) => k === kind).length;
  const busy = count("drafting") + count("queued") > 0;
  const listings = rows.filter((row) => row.creation === "created" && !row.deleted);
  const reviewed = listings.filter((row) => row.reviewed).length;
  const summaries = useListingSummaries(listings.map((row) => row.name));

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

  function deleteRecord() {
    setDeleting(false);
    deleteBatch(id)
      .then(() => navigate("/listing-templates"))
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
  const draftingPace =
    concurrency === 1
      ? "Drafting one listing at a time."
      : `Drafting up to ${concurrency} listings at a time.`;
  const settledPace =
    count("stopped") > 0 ? "Drafting stopped. Resume queues the rest." : "Drafting finished.";
  const pace = busy ? `${draftingPace} Work carries on if you close this tab.` : settledPace;

  return (
    <>
      <div className="page-head">
        <Link className="page-head__crumb" to="/listing-templates">
          Listing templates
        </Link>
        <span className="page-head__sep">/</span>
        {batch ? (
          <>
            <EditableName
              value={batch.label}
              onCommit={(label) => {
                if (label.trim() && label !== batch.label) act(renameBatch(id, label));
              }}
              label="Batch label"
              placeholder="Name this batch…"
            />
            <span className="page-head__meta">
              {isPhone ? "Tap the name to rename it" : "Double-click the label to rename it"}
            </span>
          </>
        ) : (
          <h1 className="page-head__title">Batch</h1>
        )}
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
            {count("deployed") > 0 && (
              <span className="bc-count bc-muted">
                <strong>{count("deployed")}</strong> cancelled for deploy
              </span>
            )}
            {count("deleted") > 0 && (
              <span className="bc-count bc-muted">
                <strong>{count("deleted")}</strong> deleted
              </span>
            )}
            <span className="bc-spacer" />
            <span className="bc-count">
              <strong>
                {reviewed} of {listings.length}
              </strong>{" "}
              reviewed
            </span>
            <BatchDeployReviewedButton
              batchId={id}
              deployable={rows.filter((row) => row.deployable).length}
              onError={setError}
            />
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
            Created {createdAt(batch.created_at)} from {batch.listing_template}. {pace} Briefs are
            written for you; titles, tags and the description lead wait for you to accept them in
            each listing.
          </p>

          {isPhone ? (
            <ul className="m-cards" aria-label="Listings in this batch">
              {rows.map((row, index) => (
                <PhoneRowCard
                  key={row.id}
                  batch={id}
                  row={row}
                  retryable={kinds[index] === "retry" || kinds[index] === "deployed"}
                  onReview={(next) => act(setReviewed(id, row.id, next))}
                  onRetry={() => act(retryBatchRow(id, row.id))}
                />
              ))}
            </ul>
          ) : (
            <table className="listings bc-table">
              <thead>
                <tr>
                  <th style={{ width: "22%" }}>Listing</th>
                  <th>AI drafting</th>
                  <th style={{ width: "17%" }}>SEO proposal</th>
                  <th style={{ width: "14%" }}>Reviewed</th>
                  <th className="bc-end"> </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => {
                  const open = row.creation === "created" && !row.deleted;
                  // A deploy's cancelled row has only its own Retry: Resume
                  // skips it, and it is not a failure for Retry N failed (ADR-0050).
                  const retryable = kinds[index] === "retry" || kinds[index] === "deployed";
                  return (
                    <tr key={row.id} className={open ? undefined : "bc-tr--muted"}>
                      <td>
                        <span className="bc-cell">
                          {open ? (
                            <ListingHover
                              listing={summaries.get(row.name) ?? null}
                              thumb={
                                <img
                                  className="listing-thumb"
                                  src={listingDesignThumbnailUrl(row.design)}
                                  alt=""
                                />
                              }
                            >
                              <Link className="listing-row__link" to={editorUrl(id, row)}>
                                {row.name}
                              </Link>
                            </ListingHover>
                          ) : (
                            <img
                              className="listing-thumb"
                              src={
                                row.creation === "created"
                                  ? listingDesignThumbnailUrl(row.design)
                                  : batchRowThumbnailUrl(id, row.id)
                              }
                              alt=""
                            />
                          )}
                          {!open && (
                            <span
                              className={row.deleted ? "bc-muted" : undefined}
                              style={{ fontWeight: 600 }}
                            >
                              {row.deleted ? <s>{row.name}</s> : row.name}
                            </span>
                          )}
                        </span>
                      </td>
                      <td>
                        <AiCell row={row} />
                      </td>
                      <td>
                        <ProposalCell row={row} />
                      </td>
                      <td>
                        <ReviewedCell
                          row={row}
                          onReview={(next) => act(setReviewed(id, row.id, next))}
                        />
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
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}

          <div className="bc-row bc-delete-record" style={{ marginTop: "var(--space-4)" }}>
            <span className="bc-small bc-muted">
              Deleting the batch record keeps every listing, design and brief it created.
            </span>
            <button type="button" className="bc-quiet" onClick={() => setDeleting(true)}>
              <TrashIcon
                className="bc-icon"
                style={{ width: 12, height: 12, verticalAlign: -2, marginRight: 4 }}
              />
              Delete batch record
            </button>
          </div>
        </>
      )}

      {deleting && (
        <ConfirmDialog
          title={`Delete the record of ${batch?.label ?? "this batch"}?`}
          confirmLabel="Delete record"
          details={DELETE_DETAILS}
          onConfirm={deleteRecord}
          onCancel={() => setDeleting(false)}
        />
      )}
    </>
  );
}
