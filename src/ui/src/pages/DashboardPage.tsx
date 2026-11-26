import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { listListings } from "../api/listings";
import { STATUS_LABELS } from "../components/StatusTag";
import { useIsPhone } from "../phone/usePhone";
import type { ListingStatus, ListingSummary } from "../types";

export function DashboardPage() {
  const navigate = useNavigate();
  const [listings, setListings] = useState<ListingSummary[] | null>(null);
  const [status, setStatus] = useState("");
  const isPhone = useIsPhone();

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

      {listings !== null && (
        <div className="stat-row">
          {CARDS.map((card) => {
            const body = (
              <>
                <span className="stat-card__label">{STATUS_LABELS[card.status]}</span>
                <span className="stat-card__value">{counts(card.status)}</span>
                <span className="stat-card__caption">{card.caption}</span>
              </>
            );
            return isPhone ? (
              <Link
                key={card.status}
                className="card stat-card stat-card--link"
                to={`/listings?status=${card.status}`}
              >
                {body}
              </Link>
            ) : (
              <div key={card.status} className="card stat-card">
                {body}
              </div>
            );
          })}
        </div>
      )}

      <p className="app__status" role="status">
        {status}
      </p>
    </div>
  );
}
