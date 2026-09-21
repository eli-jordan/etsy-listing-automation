import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  deleteListing,
  listingDesignThumbnailUrl,
  listListings,
  patchListing,
} from "../api/listings";
import { createRun, currentWorkspaceRun, getRun } from "../api/runs";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { OpenOnMenu } from "../components/OpenOnMenu";
import { hasOpenTargets } from "../components/openOn";
import { STATUS_LABELS, StatusTag } from "../components/StatusTag";
import type { ListingStatus, ListingSummary } from "../types";
import { BatchCandidateControl } from "./batchDeploy/BatchCandidateControl";
import { candidateNames } from "./batchDeploy/batchDeployPresentation";
import { TERMINAL_PHASES } from "./deploy/runPhases";

type Gesture = ListingSummary["gestures"][number];

const GESTURE_LABELS: Record<Gesture, string> = {
  delete: "Delete",
  retire: "Retire",
  "un-retire": "Un-retire",
  cancel: "Cancel",
  renew: "Renew",
};

const MARK_FOR_DELETION_DETAILS =
  "The listing stays in this table as pending-delete. The next apply will retract the Printify product — the Etsy draft goes with it — then remove the local files. Until then you can undo the mark.";

const DELETE_DETAILS =
  "The listing folder and its render cache are removed now. There is nothing on Printify or Etsy to retract. Designs, garment profiles and pricing plans stay.";

/** The listings list (phase 5): table + search + status filter, from
 * the design mockup's listings section, backed by `GET /api/listings`. */

type Filter = "all" | ListingStatus;

/** One option per state the server can report, plus All -- derived from
 * `STATUS_LABELS` rather than listed again, so a fifth state cannot arrive
 * with a badge and no way to filter for it. */
const FILTERS: Filter[] = ["all", ...(Object.keys(STATUS_LABELS) as ListingStatus[])];

const FILTER_LABELS: Record<Filter, string> = { all: "All statuses", ...STATUS_LABELS };

function hasRemotes(row: ListingSummary): boolean {
  return row.etsy_listing_id != null || row.printify_product_id != null;
}

function deleteLabel(row: ListingSummary): string {
  return hasRemotes(row) ? "Mark for deletion" : "Delete";
}

function gestureLabel(row: ListingSummary, gesture: Gesture): string {
  return gesture === "delete" ? deleteLabel(row) : GESTURE_LABELS[gesture];
}

/** The listing's artwork, or an empty tile when `design` is null -- which is
 * what a multi-artwork listing (`on-light`/`on-dark`) reports, since no single
 * picture stands for it. Decorative: the row's name is right beside it and is
 * what a screen reader should read, so `alt` is deliberately empty. */
function DesignThumb({ design }: { design: string | null }) {
  if (design === null) return <span className="listing-thumb listing-thumb--empty" />;
  return (
    <img className="listing-thumb" src={listingDesignThumbnailUrl(design)} alt="" loading="lazy" />
  );
}

/** The card the row's name reveals on hover. Purely CSS-driven (see
 * `.listing-hover:hover .listing-popup`) rather than JS state: it shows only
 * what the server already sent for this row, so there is nothing to fetch and
 * no state worth re-rendering the table for. It exists because the table is
 * three narrow columns and the artwork and colour count have nowhere to go. */
function ListingCard({ row }: { row: ListingSummary }) {
  return (
    <span className="listing-popup">
      {row.design !== null && (
        <img
          className="listing-popup__thumb"
          src={listingDesignThumbnailUrl(row.design)}
          alt=""
          loading="lazy"
        />
      )}
      <span className="listing-popup__name">{row.name}</span>
      <span className="listing-popup__garment">{row.garment_profile}</span>
      <span className="listing-popup__meta">
        <StatusTag status={row.status} />
        <span>
          {row.colour_count} {row.colour_count === 1 ? "colour" : "colours"}
        </span>
      </span>
    </span>
  );
}

function UndoMarkIcon() {
  return (
    <svg viewBox="0 0 14 16" aria-hidden="true">
      <path
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M5.4 2.6 2.2 5.6l3.2 3M2.2 5.6h7.6A3.1 3.1 0 0 1 9.8 11.8H4.2"
      />
    </svg>
  );
}

export function ListingsPage() {
  const [listings, setListings] = useState<ListingSummary[]>([]);
  const [workspaceRun, setWorkspaceRun] =
    useState<Awaited<ReturnType<typeof currentWorkspaceRun>>>(null);
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [pendingDelete, setPendingDelete] = useState<ListingSummary | null>(null);
  const navigate = useNavigate();

  const refresh = useCallback(() => {
    listListings()
      .then((loaded) => {
        setListings(loaded);
        setStatus("");
      })
      .catch(() => setStatus("failed to load listings"));
    currentWorkspaceRun()
      .then(setWorkspaceRun)
      .catch(() => setWorkspaceRun(null));
  }, []);

  const startBatchPlan = useCallback(async () => {
    setStatus("");
    try {
      const result = await createRun({ kind: "plan", scope: "workspace" });
      if (result.kind === "created") {
        navigate(`/listings/deploy/${encodeURIComponent(result.run.id)}`);
        return;
      }
      const conflict = await getRun(result.activeRun);
      if (conflict.scope === "workspace") {
        navigate(`/listings/deploy/${encodeURIComponent(conflict.id)}`);
      } else {
        setStatus("A listing deploy is already running. Open that listing to follow it.");
      }
    } catch {
      setStatus("could not start a workspace plan");
    }
  }, [navigate]);

  const workspaceAction = useMemo(() => {
    if (workspaceRun === null) return null;
    if (workspaceRun.kind === "apply" && !TERMINAL_PHASES.has(workspaceRun.phase)) {
      return { label: "View batch progress", prefix: "Deploying…" };
    }
    if (!TERMINAL_PHASES.has(workspaceRun.phase)) {
      return { label: "View batch progress", prefix: "Planning…" };
    }
    if (workspaceRun.kind === "apply" && !workspaceRun.seen && workspaceRun.phase === "applied") {
      return { label: "View batch result", prefix: "Deployed ✓" };
    }
    if (
      workspaceRun.kind === "apply" &&
      !workspaceRun.seen &&
      (workspaceRun.phase === "failed" || workspaceRun.phase === "stale")
    ) {
      return { label: "View batch result", prefix: "Deploy failed" };
    }
    if (!workspaceRun.seen && workspaceRun.phase === "ready") {
      return { label: "View batch review", prefix: "Review ready" };
    }
    if (!workspaceRun.seen && workspaceRun.phase === "failed") {
      return { label: "View batch result", prefix: "Deploy failed" };
    }
    return null;
  }, [workspaceRun]);

  const runGesture = useCallback(
    async (row: ListingSummary, gesture: Gesture) => {
      if (gesture === "delete") {
        setPendingDelete(row);
        return;
      }
      const lifecycle = gesture === "retire" ? "retired" : gesture === "renew" ? "renew" : null;
      try {
        await patchListing(row.name, { lifecycle });
        refresh();
      } catch {
        setStatus(`could not ${GESTURE_LABELS[gesture].toLowerCase()} ${row.name}`);
      }
    },
    [refresh],
  );

  const confirmDelete = useCallback(async () => {
    if (pendingDelete === null) return;
    const name = pendingDelete.name;
    setPendingDelete(null);
    try {
      await deleteListing(name);
      refresh();
    } catch {
      setStatus(`could not delete ${name}`);
    }
  }, [pendingDelete, refresh]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (workspaceRun === null || TERMINAL_PHASES.has(workspaceRun.phase)) return;
    const interval = window.setInterval(refresh, 500);
    return () => window.clearInterval(interval);
  }, [refresh, workspaceRun]);

  const rows = useMemo(
    () =>
      listings
        .filter((l) => filter === "all" || l.status === filter)
        .filter((l) => l.name.toLowerCase().includes(query.toLowerCase())),
    [listings, filter, query],
  );

  return (
    <div>
      <div className="page-head">
        <h1 className="page-head__title">Listings</h1>
        <span className="page-head__meta">{rows.length} shown</span>
        <div className="page-head__actions">
          {workspaceAction !== null && workspaceRun !== null && (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => navigate(`/listings/deploy/${encodeURIComponent(workspaceRun.id)}`)}
            >
              {workspaceAction.prefix} · {workspaceAction.label} →
            </button>
          )}
          <BatchCandidateControl
            names={candidateNames(listings)}
            onDeploy={() => void startBatchPlan()}
          />
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => navigate("/listings/new")}
          >
            + New listing
          </button>
        </div>
      </div>

      <div className="toolbar">
        <input
          className="input toolbar__search"
          type="text"
          placeholder="Search listings…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <label className="toolbar__filter">
          <span className="toolbar__filter-label">Status</span>
          <select
            className="input"
            value={filter}
            onChange={(event) => setFilter(event.target.value as Filter)}
          >
            {FILTERS.map((f) => (
              <option key={f} value={f}>
                {FILTER_LABELS[f]}
              </option>
            ))}
          </select>
        </label>
      </div>

      <p className="app__status" role="status">
        {status}
      </p>

      <table className="listings">
        <thead>
          <tr>
            <th>Listing</th>
            <th>Garment</th>
            <th>Status</th>
            <th className="listings__actions"> </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.name}>
              <td>
                <div className="listing-cell">
                  <span className="listing-hover">
                    <DesignThumb design={row.design} />
                    <button
                      type="button"
                      className="listing-row__link"
                      onClick={() => navigate(`/listings/${encodeURIComponent(row.name)}`)}
                    >
                      {row.name}
                    </button>
                    <ListingCard row={row} />
                  </span>
                  {hasOpenTargets(row.etsy_listing_id, row.printify_product_id) && (
                    <OpenOnMenu
                      etsyListingId={row.etsy_listing_id}
                      printifyProductId={row.printify_product_id}
                    />
                  )}
                  {row.issue_counts.block > 0 && (
                    <span className="tab-badge tab-badge--block">{row.issue_counts.block}</span>
                  )}
                  {row.issue_counts.block === 0 && row.issue_counts.warn > 0 && (
                    <span className="tab-badge tab-badge--warn">{row.issue_counts.warn}</span>
                  )}
                </div>
              </td>
              <td className="listing-row__garment">{row.garment_profile}</td>
              <td>
                <span className="listings__status">
                  <StatusTag status={row.status} />
                  {(row.gestures ?? []).includes("cancel") && (
                    <span className="status-tag">
                      <button
                        type="button"
                        className="listings__undo"
                        aria-label="Undo mark for delete"
                        onClick={() => void runGesture(row, "cancel")}
                      >
                        <UndoMarkIcon />
                      </button>
                      <span className="status-tag__hint" role="tooltip">
                        Undo mark for delete
                      </span>
                    </span>
                  )}
                </span>
              </td>
              <td className="listings__actions">
                {(row.gestures ?? [])
                  .filter((gesture) => gesture !== "cancel")
                  .map((gesture) => (
                    <button
                      key={gesture}
                      type="button"
                      className={gesture === "delete" ? "listings__quiet" : "btn btn-ghost"}
                      onClick={() => void runGesture(row, gesture)}
                    >
                      {gestureLabel(row, gesture)}
                    </button>
                  ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {rows.length === 0 && !status && <p className="text-muted">No listings match.</p>}

      {pendingDelete !== null && (
        <ConfirmDialog
          title={
            hasRemotes(pendingDelete)
              ? `Are you sure you want to mark ${pendingDelete.name} for deletion?`
              : `Are you sure you want to delete ${pendingDelete.name}?`
          }
          confirmLabel={deleteLabel(pendingDelete)}
          details={hasRemotes(pendingDelete) ? MARK_FOR_DELETION_DETAILS : DELETE_DETAILS}
          onConfirm={() => void confirmDelete()}
          onCancel={() => setPendingDelete(null)}
        />
      )}
    </div>
  );
}
