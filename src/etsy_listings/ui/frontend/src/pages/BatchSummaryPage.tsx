import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { ClockIcon } from "@phosphor-icons/react/dist/csr/Clock";
import { WarningCircleIcon } from "@phosphor-icons/react/dist/csr/WarningCircle";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getBatch, retryBatchRow, type BatchDetail, type BatchRow } from "../api/batches";
import { listingDesignThumbnailUrl } from "../api/listings";

/**
 * The batch summary (UI doc §7; the `batch-summary` frame), in its first,
 * minimal slice (batch plan PR 2): the label, then one row per listing with
 * the name actually created, its creation state, Retry for a row that failed
 * and Open for one that exists. The progress bar, AI column and queue
 * controls come with the batch queue (PR 4); Reviewed, rename and delete
 * with review (PR 5).
 */

function time(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

function Creation({ row }: { row: BatchRow }) {
  if (row.creation === "created") {
    return (
      <span className="bc-status bc-status--ok">
        <CheckCircleIcon className="bc-icon" />
        Listing created
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
  return (
    <span className="bc-status bc-status--info">
      <ClockIcon className="bc-icon" />
      Not created yet
    </span>
  );
}

export function BatchSummaryPage() {
  const { id = "" } = useParams();
  const [batch, setBatch] = useState<BatchDetail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    getBatch(id)
      .then((loaded) => current && setBatch(loaded))
      .catch((exc: Error) => current && setError(exc.message));
    return () => {
      current = false;
    };
  }, [id]);

  function retry(row: string) {
    retryBatchRow(id, row)
      .then((next) => {
        setError("");
        setBatch(next);
      })
      .catch((exc: Error) => setError(exc.message));
  }

  const rows = batch?.rows ?? [];
  const created = rows.filter((row) => row.creation === "created").length;

  return (
    <>
      <div className="page-head">
        <Link className="page-head__crumb" to="/listing-templates">
          Listing templates
        </Link>
        <span className="page-head__sep">/</span>
        <h1 className="page-head__title">{batch?.label ?? "Batch"}</h1>
      </div>

      {error && (
        <p className="app__status" role="alert">
          {error}
        </p>
      )}

      {batch && (
        <>
          <p className="bc-small bc-muted" style={{ margin: "0 0 var(--space-3)" }}>
            Created at {time(batch.created_at)} from {batch.listing_template}. {created} of{" "}
            {rows.length} listings created. Each one is a local draft; nothing goes to Printify or
            Etsy.
          </p>

          <table className="listings bc-table">
            <thead>
              <tr>
                <th style={{ width: "30%" }}>Listing</th>
                <th>Created</th>
                <th className="bc-end"> </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const exists = row.creation === "created";
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
                      <Creation row={row} />
                    </td>
                    <td className="bc-end">
                      {row.creation === "failed" && (
                        <button
                          type="button"
                          className="btn btn-ghost"
                          onClick={() => retry(row.id)}
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
