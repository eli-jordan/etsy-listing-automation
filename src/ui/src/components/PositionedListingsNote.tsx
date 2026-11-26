import { useEffect, useState } from "react";
import { getPositionedListings, type PositionedListing } from "../api/calibrator";
import { useIsPhone } from "../phone/usePhone";

export function PositionedListingsNote({
  templateName,
  savedAt,
}: {
  templateName: string;
  savedAt: number | null;
}) {
  const phone = useIsPhone();
  const [held, setHeld] = useState<{ template: string; listings: PositionedListing[] } | null>(
    null,
  );

  useEffect(() => {
    let live = true;
    getPositionedListings(templateName)
      .then((listings) => {
        if (live) setHeld({ template: templateName, listings });
      })
      .catch(() => {
        if (live) setHeld(null);
      });
    return () => {
      live = false;
    };
  }, [templateName, savedAt]);

  if (!held || held.template !== templateName || held.listings.length === 0) return null;
  const count = held.listings.length;
  const names = held.listings
    .map(({ listing, placements }) =>
      placements.length ? `${listing} (${placements.join(", ")})` : listing,
    )
    .join(", ");
  const them = count === 1 ? "it" : "them";
  const lead = count === 1 ? "1 listing holds its" : `${count} listings hold their`;
  if (phone) {
    return (
      <details className="app__warn app__positions-note app__positions-note--phone" role="note">
        <summary>{`${lead} own position on this template`}</summary>
        <p>
          {names}. Changing the box does not move {them}; the next plan re-checks {them} against the
          position limits.
        </p>
      </details>
    );
  }
  return (
    <p className="app__warn app__positions-note" role="note">
      {count === 1 ? "1 listing holds its" : `${count} listings hold their`} own position on this
      template: {names}. Changing the box does not move {them}; the next plan re-checks {them}{" "}
      against the position limits.
    </p>
  );
}
