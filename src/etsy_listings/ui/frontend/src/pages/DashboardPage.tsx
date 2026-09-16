import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listListings } from "../api/listings";
import { STATUS_LABELS } from "../components/StatusTag";
import type { ListingStatus, ListingSummary } from "../types";

/**
 * The counts the workspace already knows, from the mockup's Dashboard.
 *
 * One card per lifecycle state (`engine/status.py`), because the three that
 * are not "live" are three different pieces of news: `draft` is work not yet
 * pushed anywhere, `deployed` is work waiting on a human to press publish in
 * Shop Manager, and `dirty` is a live listing whose copy has moved on. A
 * single "not published" number would hide the only one of those that is
 * about something buyers can see.
 *
 * Deliberately not a second listings table: `GET /api/listings` derives
 * `status` per row on every read, so the counts cost nothing beyond the
 * request the Listings page makes anyway -- and anything richer (last run,
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

  const counts = (status: ListingStatus) =>
    listings?.filter((l) => l.status === status).length ?? 0;

  const CARDS: { status: ListingStatus; caption: string }[] = [
    { status: "draft", caption: "not applied yet" },
    { status: "deployed", caption: "applied — publish on Etsy" },
    { status: "live", caption: "published on Etsy" },
    { status: "dirty", caption: "live, but edited since" },
  ];

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
          {CARDS.map((card) => (
            <div key={card.status} className="card stat-card">
              <span className="stat-card__label">{STATUS_LABELS[card.status]}</span>
              <span className="stat-card__value">{counts(card.status)}</span>
              <span className="stat-card__caption">{card.caption}</span>
            </div>
          ))}
        </div>
      )}

      <p className="app__status" role="status">
        {status}
      </p>
    </div>
  );
}
