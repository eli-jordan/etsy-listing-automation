import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { deleteListing, listListings, patchListing } from "../api/listings";
import { createRun, currentWorkspaceRun, getRun, isReviewedScope } from "../api/runs";
import { reviewRunAction } from "./batchDeploy/reviewRunAction";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { ListingHover } from "../components/ListingHover";
import { OpenInMenu } from "../components/OpenInMenu";
import { hasOpenTargets } from "../components/openOn";
import { STATUS_LABELS, StatusTag } from "../components/StatusTag";
import { useIsPhone, useIsPhoneLandscape } from "../phone/usePhone";
import type { ListingStatus, ListingSummary } from "../types";
import { BatchCandidateControl } from "./batchDeploy/BatchCandidateControl";
import { candidateNames } from "./batchDeploy/batchDeployPresentation";
import { TERMINAL_PHASES } from "./deploy/runPhases";
import { lastLoadedListings, rememberLoadedListings } from "./loadedListings";
import {
  deleteDetails,
  deleteLabel,
  deleteTitle,
  GESTURE_LABELS,
  type Gesture,
  LIFECYCLE_OF,
} from "./listingLifecycle";
import { useFabHiddenOnScroll } from "./phoneLists/fabScroll";
import { PhoneListingList, PhoneStatusChips } from "./phoneLists/PhoneListingList";

type Filter = "all" | ListingStatus;

const FILTERS: Filter[] = ["all", ...(Object.keys(STATUS_LABELS) as ListingStatus[])];

const FILTER_LABELS: Record<Filter, string> = { all: "All statuses", ...STATUS_LABELS };

function filterFrom(param: string | null): Filter {
  return FILTERS.find((f) => f === param) ?? "all";
}

function gestureLabel(row: ListingSummary, gesture: Gesture): string {
  return gesture === "delete" ? deleteLabel(row) : GESTURE_LABELS[gesture];
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

function ListingsTable({
  rows,
  onGesture,
}: {
  rows: ListingSummary[];
  onGesture: (row: ListingSummary, gesture: Gesture) => void;
}) {
  const navigate = useNavigate();
  return (
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
                <ListingHover listing={row}>
                  <button
                    type="button"
                    className="listing-row__link"
                    onClick={() => navigate(`/listings/${encodeURIComponent(row.name)}`)}
                  >
                    {row.name}
                  </button>
                </ListingHover>
                {hasOpenTargets(row.etsy_listing_id, row.printify_product_id) && (
                  <OpenInMenu
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
                      onClick={() => onGesture(row, "cancel")}
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
                    onClick={() => onGesture(row, gesture)}
                  >
                    {gestureLabel(row, gesture)}
                  </button>
                ))}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function ListingsPage() {
  const [listings, setListings] = useState<ListingSummary[] | null>(lastLoadedListings);
  const [workspaceRun, setWorkspaceRun] =
    useState<Awaited<ReturnType<typeof currentWorkspaceRun>>>(null);
  const [status, setStatus] = useState("");
  const isPhone = useIsPhone();
  // On a phone the filter and the search live in the address (`?status=`,
  // `?q=`, both replaced rather than pushed), so Back from a listing comes
  // back to the same list, and a Dashboard count or the Listings tab (which
  // drops `?status=`) chooses the filter. The desktop keeps both in state.
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState(() => (isPhone ? (params.get("q") ?? "") : ""));
  const [desktopFilter, setDesktopFilter] = useState<Filter>("all");
  const filter = isPhone ? filterFrom(params.get("status")) : desktopFilter;
  // Each edit starts from the last address this page asked for, not from
  // `params`: the router answers a render later, so a chip tapped and a
  // search typed before it does would each rebuild the address from the old
  // one, and the second would put the first one's filter back.
  const latestParams = useRef(params);
  useLayoutEffect(() => {
    latestParams.current = params;
  }, [params]);
  const replaceParam = useCallback(
    (name: string, value: string) => {
      const updated = new URLSearchParams(latestParams.current);
      if (value === "") updated.delete(name);
      else updated.set(name, value);
      latestParams.current = updated;
      setParams(updated, { replace: true });
    },
    [setParams],
  );
  const setPhoneFilter = useCallback(
    (next: Filter) => replaceParam("status", next === "all" ? "" : next),
    [replaceParam],
  );
  // The search box stays local state, since the address answers a step
  // behind each keystroke, and is copied there whenever the two differ.
  const addressQuery = params.get("q") ?? "";
  useEffect(() => {
    if (!isPhone || addressQuery === query) return;
    replaceParam("q", query);
  }, [isPhone, addressQuery, query, replaceParam]);
  // New listing floats over the list on a phone held upright. Held sideways
  // the head has room for it, and so few rows show that a floating button
  // would sit on one.
  const isPhoneSideways = useIsPhoneLandscape();
  const floatingNew = isPhone && !isPhoneSideways;
  const fabHidden = useFabHiddenOnScroll(floatingNew);
  const [pendingDelete, setPendingDelete] = useState<ListingSummary | null>(null);
  const navigate = useNavigate();

  const refresh = useCallback(() => {
    listListings()
      .then((loaded) => {
        rememberLoadedListings(loaded);
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
      const result = await createRun({ kind: "plan", scope: "workspace", publish: false });
      if (result.kind === "created") {
        navigate(`/listings/deploy/${encodeURIComponent(result.run.id)}`);
        return;
      }
      const conflict = await getRun(result.activeRun);
      if (isReviewedScope(conflict)) {
        navigate(`/listings/deploy/${encodeURIComponent(conflict.id)}`);
      } else {
        setStatus("A listing deploy is already running. Open that listing to follow it.");
      }
    } catch {
      setStatus("could not start a workspace plan");
    }
  }, [navigate]);

  const workspaceAction = useMemo(() => reviewRunAction(workspaceRun), [workspaceRun]);

  const runGesture = useCallback(
    async (row: ListingSummary, gesture: Gesture) => {
      if (gesture === "delete") {
        setPendingDelete(row);
        return;
      }
      try {
        await patchListing(row.name, { lifecycle: LIFECYCLE_OF[gesture] });
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
      (listings ?? [])
        .filter((l) => filter === "all" || l.status === filter)
        .filter((l) => l.name.toLowerCase().includes(query.toLowerCase())),
    [listings, filter, query],
  );

  return (
    <div>
      <div className="page-head">
        <h1 className="page-head__title">Listings</h1>
        {listings !== null && <span className="page-head__meta">{rows.length} shown</span>}
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
            names={candidateNames(listings ?? [])}
            onDeploy={() => void startBatchPlan()}
          />
          {!floatingNew && (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => navigate("/listings/new")}
            >
              + New listing
            </button>
          )}
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
        {isPhone ? (
          listings !== null && (
            <PhoneStatusChips listings={listings} value={filter} onChange={setPhoneFilter} />
          )
        ) : (
          <label className="toolbar__filter">
            <span className="toolbar__filter-label">Status</span>
            <select
              className="input"
              value={filter}
              onChange={(event) => setDesktopFilter(event.target.value as Filter)}
            >
              {FILTERS.map((f) => (
                <option key={f} value={f}>
                  {FILTER_LABELS[f]}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <p className="app__status" role="status">
        {status}
      </p>

      {isPhone ? (
        <PhoneListingList
          rows={rows}
          onOpen={(row) => navigate(`/listings/${encodeURIComponent(row.name)}`)}
          onGesture={(row, gesture) => void runGesture(row, gesture)}
        />
      ) : (
        <ListingsTable rows={rows} onGesture={(row, gesture) => void runGesture(row, gesture)} />
      )}

      {listings !== null && rows.length === 0 && !status && (
        <p className="text-muted">No listings match.</p>
      )}

      {floatingNew && (
        <button
          type="button"
          className={fabHidden ? "m-fab m-fab--hidden" : "m-fab"}
          aria-label="New listing"
          onClick={() => navigate("/listings/new")}
        >
          <span aria-hidden="true">+</span>
        </button>
      )}

      {pendingDelete !== null && (
        <ConfirmDialog
          title={deleteTitle(pendingDelete)}
          confirmLabel={deleteLabel(pendingDelete)}
          details={deleteDetails(pendingDelete)}
          onConfirm={() => void confirmDelete()}
          onCancel={() => setPendingDelete(null)}
        />
      )}
    </div>
  );
}
