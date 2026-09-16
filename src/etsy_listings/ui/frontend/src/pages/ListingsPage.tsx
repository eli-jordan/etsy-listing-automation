import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listingDesignThumbnailUrl, listListings } from "../api/listings";
import { OpenOnMenu } from "../components/OpenOnMenu";
import { hasOpenTargets } from "../components/openOn";
import { STATUS_LABELS, StatusTag } from "../components/StatusTag";
import type { ListingStatus, ListingSummary } from "../types";

/** The listings list (phase 5): table + search + status filter pills, from
 * the design mockup's listings section, backed by `GET /api/listings`. */

type Filter = "all" | ListingStatus;

/** One pill per state the server can report, plus All -- derived from
 * `STATUS_LABELS` rather than listed again, so a fifth state cannot arrive
 * with a badge and no way to filter for it. */
const FILTERS: Filter[] = ["all", ...(Object.keys(STATUS_LABELS) as ListingStatus[])];

const FILTER_LABELS: Record<Filter, string> = { all: "All", ...STATUS_LABELS };

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

export function ListingsPage() {
  const [listings, setListings] = useState<ListingSummary[]>([]);
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const navigate = useNavigate();

  const refresh = useCallback(() => {
    listListings()
      .then((loaded) => {
        setListings(loaded);
        setStatus("");
      })
      .catch(() => setStatus("failed to load listings"));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

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
        {FILTERS.map((f) => (
          <button
            key={f}
            type="button"
            className={filter === f ? "pill pill--on" : "pill"}
            onClick={() => setFilter(f)}
          >
            {FILTER_LABELS[f]}
          </button>
        ))}
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
                <StatusTag status={row.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {rows.length === 0 && !status && <p className="text-muted">No listings match.</p>}
    </div>
  );
}
