import { useState } from "react";
import { DesignThumb } from "../../components/ListingHover";
import { STATUS_LABELS, StatusTag } from "../../components/StatusTag";
import type { ListingStatus, ListingSummary } from "../../types";
import type { Gesture } from "../listingLifecycle";
import { ActionSheet } from "./ActionSheet";
import { rowActions } from "./rowActions";

/**
 * The Listings table as a phone list: one row per listing, the whole row a
 * tap target that opens it, and what the table's row carries inline (the
 * Open in menu, the lifecycle gestures, Undo mark for delete) behind a
 * trailing ⋯ that opens an action sheet. Rendered only by the phone layout.
 */

function IssueBadge({ row }: { row: ListingSummary }) {
  if (row.issue_counts.block > 0) {
    return <span className="tab-badge tab-badge--block">{row.issue_counts.block}</span>;
  }
  if (row.issue_counts.warn > 0) {
    return <span className="tab-badge tab-badge--warn">{row.issue_counts.warn}</span>;
  }
  return null;
}

export function PhoneListingList({
  rows,
  onOpen,
  onGesture,
}: {
  rows: ListingSummary[];
  onOpen: (row: ListingSummary) => void;
  onGesture: (row: ListingSummary, gesture: Gesture) => void;
}) {
  const [sheetFor, setSheetFor] = useState<ListingSummary | null>(null);
  const sheetActions = sheetFor === null ? [] : rowActions(sheetFor, onGesture);

  return (
    <>
      <ul className="m-list" aria-label="Listings">
        {rows.map((row) => {
          const actions = rowActions(row, onGesture);
          return (
            <li key={row.name} className="m-row">
              <button type="button" className="m-row__main" onClick={() => onOpen(row)}>
                <DesignThumb design={row.design} />
                <span className="m-row__text">
                  <span className="m-row__name">{row.name}</span>
                  <span className="m-row__sub">
                    <IssueBadge row={row} />
                    {row.garment_profile}
                  </span>
                </span>
                <StatusTag status={row.status} />
              </button>
              {actions.length > 0 && (
                <button
                  type="button"
                  className="m-row__more"
                  aria-label={`More actions for ${row.name}`}
                  onClick={() => setSheetFor(row)}
                >
                  <span aria-hidden="true">⋯</span>
                </button>
              )}
            </li>
          );
        })}
      </ul>
      {sheetFor !== null && (
        <ActionSheet
          title={sheetFor.name}
          actions={sheetActions}
          onClose={() => setSheetFor(null)}
        />
      )}
    </>
  );
}

/**
 * The status filter as a row of chips, one tap each instead of a select:
 * All, then every state that some listing is in (plus the chosen one, so
 * a filter that empties never strands its own chip), each with its count.
 */
export function PhoneStatusChips<F extends "all" | ListingStatus>({
  listings,
  value,
  onChange,
}: {
  listings: ListingSummary[];
  value: F;
  onChange: (next: F) => void;
}) {
  const counts = new Map<ListingStatus, number>();
  for (const listing of listings) counts.set(listing.status, (counts.get(listing.status) ?? 0) + 1);
  const states = (Object.keys(STATUS_LABELS) as ListingStatus[]).filter(
    (status) => counts.has(status) || status === value,
  );
  const chips: { key: F; label: string; count: number }[] = [
    { key: "all" as F, label: "All", count: listings.length },
    ...states.map((status) => ({
      key: status as F,
      label: STATUS_LABELS[status],
      count: counts.get(status) ?? 0,
    })),
  ];
  return (
    <div className="m-chips" role="radiogroup" aria-label="Status">
      {chips.map((chip) => (
        <button
          key={chip.key}
          type="button"
          role="radio"
          aria-checked={chip.key === value}
          className={chip.key === value ? "m-chip m-chip--on" : "m-chip"}
          onClick={() => onChange(chip.key)}
        >
          {chip.label}
          <span className="m-chip__count">{chip.count}</span>
        </button>
      ))}
    </div>
  );
}
