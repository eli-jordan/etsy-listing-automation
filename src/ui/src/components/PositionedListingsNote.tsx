import { useEffect, useState } from "react";
import { getPositionedListings, type PositionedListing } from "../api/calibrator";
import { useIsPhone } from "../phone/usePhone";

/** The listings holding their own position on the open template (spec,
 * *Recalibration*), so the seller sees what a box change may break before the
 * autosave writes it and again once it has. Positions are absolute: the
 * calibrator never moves or edits them, and the next plan re-checks them.
 *
 * `savedAt` re-reads the list after each save, since listings may have
 * changed meanwhile. A failed read shows nothing: the note is advice, and the
 * plan still refuses an out-of-limits position. */
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

  // A list read for the previous template must not show under this one.
  if (!held || held.template !== templateName || held.listings.length === 0) return null;
  const count = held.listings.length;
  const names = held.listings
    .map(({ listing, placements }) =>
      placements.length ? `${listing} (${placements.join(", ")})` : listing,
    )
    .join(", ");
  const them = count === 1 ? "it" : "them";
  const lead = count === 1 ? "1 listing holds its" : `${count} listings hold their`;
  // On a phone the full list pushed the photo a screen down; the count says
  // what matters, and the names are a tap away.
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
      {lead} own position on this template: {names}. Changing the box does not move {them}; the next
      plan re-checks {them} against the position limits.
    </p>
  );
}
