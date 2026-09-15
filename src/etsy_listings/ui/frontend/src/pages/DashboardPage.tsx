import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listListings } from "../api/listings";
import type { ListingSummary } from "../types";

/**
 * The two counts the workspace already knows, from the mockup's Dashboard.
 *
 * Deliberately not a second listings table: `GET /api/listings` derives
 * `status` per row on every read, so published-vs-draft costs nothing beyond
 * the request the Listings page makes anyway -- and anything richer (last run,
 * what a `plan` would do) needs the Runner, which is a later pass.
 */

export function DashboardPage() {
  const navigate = useNavigate();
  const [listings, setListings] = useState<ListingSummary[] | null>(null);
  const [status, setStatus] = useState("");

  useEffect(() => {
    listListings()
      .then(setListings)
      .catch(() => setStatus("failed to load listings"));
  }, []);

  const published = listings?.filter((l) => l.status === "published").length ?? 0;
  const drafts = (listings?.length ?? 0) - published;

  return (
    <div>
      <div className="page-head">
        <h1 className="page-head__title">Dashboard</h1>
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

      {/* Nothing until the counts are real: a dashboard showing 0/0 while the
          request is still in flight states something false. */}
      {listings !== null && (
        <div className="stat-row">
          <div className="card stat-card">
            <span className="stat-card__label">Published</span>
            <span className="stat-card__value">{published}</span>
            <span className="stat-card__caption">live on Etsy</span>
          </div>
          <div className="card stat-card">
            <span className="stat-card__label">Drafts</span>
            <span className="stat-card__value">{drafts}</span>
            <span className="stat-card__caption">not yet published</span>
          </div>
        </div>
      )}

      <p className="app__status" role="status">
        {status}
      </p>
    </div>
  );
}
