import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { listBatches, type BatchIndexEntry, type BatchStatus } from "../api/batches";
import { clock, dayMonth } from "../dates";

/**
 * Recent batches (UI doc §2; the `templates` frame): every batch and every
 * unconfirmed staging session, each with a status the server derives from
 * its rows (`batches.standing`) and never set by hand. A Staging row
 * reopens staging; every other row opens the batch summary.
 *
 * Failures are not a status: they are the red *N need retry* beside the
 * progress, so a batch with one failed row still reads as Drafting or In
 * review.
 */

const STATUS: Record<BatchStatus, { label: string; className: string }> = {
  staging: { label: "Staging", className: "tag tag-neutral" },
  drafting: { label: "Drafting", className: "tag tag-accent" },
  in_review: { label: "In review", className: "tag tag-accent" },
  complete: { label: "Complete", className: "tag tag-accent-2" },
  stopped: { label: "Stopped", className: "tag tag-neutral" },
};

export function BatchStatusTag({ status }: { status: BatchStatus }) {
  const { label, className } = STATUS[status];
  return (
    <span className={className} style={{ gap: 5 }}>
      {status === "drafting" && (
        <span className="dv-spinner" style={{ width: 9, height: 9, borderWidth: 1.5 }} />
      )}
      {label}
    </span>
  );
}

function day(iso: string): string {
  return dayMonth(new Date(iso));
}

function created(iso: string): string {
  const when = new Date(iso);
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  if (when.toDateString() === new Date().toDateString()) {
    return `Today ${clock(when)}`;
  }
  if (when.toDateString() === yesterday.toDateString()) return "Yesterday";
  return day(iso);
}

/** The Progress column, in the frame's words for each status. */
function batchProgress(entry: BatchIndexEntry): string {
  const reviewed = `${entry.reviewed} of ${entry.listings} reviewed`;
  switch (entry.status) {
    case "staging": {
      const kept = entry.expires_at ? ` · kept until ${day(entry.expires_at)}` : "";
      const designs = `${entry.designs} ${entry.designs === 1 ? "design" : "designs"}`;
      return `${designs}, not created yet${kept}`;
    }
    case "drafting":
      return `${entry.drafted} of ${entry.listings} drafted · ${reviewed}`;
    case "stopped":
      return `Cancelled with ${entry.undrafted} left to draft · ${reviewed}`;
    default:
      return reviewed;
  }
}

function destination(entry: BatchIndexEntry): string {
  const id = encodeURIComponent(entry.id);
  return entry.kind === "staging" ? `/batches/staging/${id}` : `/batches/${id}`;
}

export function RecentBatches() {
  const [entries, setEntries] = useState<BatchIndexEntry[]>([]);
  const navigate = useNavigate();

  useEffect(() => {
    let current = true;
    listBatches()
      .then((loaded) => current && setEntries(loaded))
      // The cards above are the page; a batch index that will not load
      // leaves them usable rather than replacing them with an error.
      .catch(() => {});
    return () => {
      current = false;
    };
  }, []);

  if (entries.length === 0) return null;

  return (
    <section className="bc-section">
      <h2>Recent batches</h2>
      <table className="listings bc-table">
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
          {entries.map((entry) => (
            <tr
              key={`${entry.kind}-${entry.id}`}
              className="bc-tr--link"
              onClick={() => navigate(destination(entry))}
            >
              <td style={{ whiteSpace: "nowrap" }}>
                <Link
                  className="listing-row__link"
                  to={destination(entry)}
                  onClick={(event) => event.stopPropagation()}
                >
                  {entry.label}
                </Link>
              </td>
              <td>
                <BatchStatusTag status={entry.status} />
              </td>
              <td>
                {batchProgress(entry)}
                {entry.failures > 0 && (
                  <span className="bc-status bc-status--error" style={{ marginLeft: 8 }}>
                    <span className="bc-dot bc-dot--error" style={{ marginTop: 5 }} />
                    {entry.failures} {entry.failures === 1 ? "needs" : "need"} retry
                  </span>
                )}
              </td>
              <td className="bc-muted" style={{ whiteSpace: "nowrap" }}>
                {entry.listing_template}
              </td>
              <td className="bc-muted" style={{ whiteSpace: "nowrap" }}>
                {created(entry.created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
