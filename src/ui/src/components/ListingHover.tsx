import type { ReactNode } from "react";
import { listingDesignThumbnailUrl } from "../api/listings";
import type { ListingSummary } from "../types";
import { StatusTag } from "./StatusTag";

/** Decorative: the row's name beside it is what a screen reader reads. */
export function DesignThumb({ design }: { design: string | null }) {
  if (design === null) return <span className="listing-thumb listing-thumb--empty" />;
  return (
    <img className="listing-thumb" src={listingDesignThumbnailUrl(design)} alt="" loading="lazy" />
  );
}

/** Shown by CSS on hover (`.listing-hover:hover .listing-popup`). */
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

export function ListingHover({
  listing,
  thumb,
  children,
}: {
  listing: ListingSummary | null;
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
