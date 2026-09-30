import type { ReactNode } from "react";
import { listingDesignThumbnailUrl } from "../api/listings";
import type { ListingSummary } from "../types";
import { StatusTag } from "./StatusTag";

/** The listing's artwork, or an empty tile when `design` is null -- which is
 * what a multi-artwork listing (`on-light`/`on-dark`) reports, since no single
 * picture stands for it. Decorative: the row's name is right beside it and is
 * what a screen reader should read, so `alt` is deliberately empty. */
export function DesignThumb({ design }: { design: string | null }) {
  if (design === null) return <span className="listing-thumb listing-thumb--empty" />;
  return (
    <img className="listing-thumb" src={listingDesignThumbnailUrl(design)} alt="" loading="lazy" />
  );
}

/** The card the row's name reveals on hover. Purely CSS-driven (see
 * `.listing-hover:hover .listing-popup`) rather than JS state: it shows only
 * what the server already sent for this row, so there is nothing to fetch and
 * no state worth re-rendering the table for. It exists because a table row is
 * narrow and the artwork and colour count have nowhere to go. */
function ListingCard({ listing }: { listing: ListingSummary }) {
  return (
    <span className="listing-popup">
      {listing.design !== null && (
        <img
          className="listing-popup__thumb"
          src={listingDesignThumbnailUrl(listing.design)}
          alt=""
          loading="lazy"
        />
      )}
      <span className="listing-popup__name">{listing.name}</span>
      <span className="listing-popup__garment">{listing.garment_profile}</span>
      <span className="listing-popup__meta">
        <StatusTag status={listing.status} />
        <span>
          {listing.colour_count} {listing.colour_count === 1 ? "colour" : "colours"}
        </span>
      </span>
    </span>
  );
}

/**
 * A listing's name in a table -- its thumbnail, the name itself (`children`,
 * the caller's link or button styled `listing-row__link`) and the hover card
 * -- the same on every table that lists listings: the Listings page and a
 * batch summary. Without a `listing` summary (not loaded yet) it is the
 * thumbnail and the name alone.
 */
export function ListingHover({
  listing,
  thumb,
  children,
}: {
  listing: ListingSummary | null;
  /** The thumbnail when there is no summary to draw it from. */
  thumb?: ReactNode;
  children: ReactNode;
}) {
  return (
    <span className="listing-hover">
      {listing !== null ? <DesignThumb design={listing.design} /> : thumb}
      {children}
      {listing !== null && <ListingCard listing={listing} />}
    </span>
  );
}
