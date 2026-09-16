import type { ReactNode } from "react";
import type { SaveState } from "../../hooks/useAutosave";
import type { ListingDetail } from "../../types";

/** What the editor's page head says about where this listing stands with the
 * disk.
 *
 * Its own module, and pure, so the five states can be read (and tested) as five
 * sentences rather than five renders.
 *
 * The "not saved yet" ones say what is in the way rather than a bland "Not
 * saved". `Listing` will not be written without a price source, so a listing
 * can have a name, a design, a garment profile and colours and still not exist
 * as a file -- and a user who is not told that watches a file never appear. */
export function metaFor(save: SaveState, detail: ListingDetail, name: string | null): ReactNode {
  switch (save.kind) {
    case "unnamed":
      return "Not saved — double-click the name above to name this listing";
    case "name-taken":
      return `There is already a listing called “${save.name}” — pick another name`;
    case "unsaved": {
      const blocking = detail.issues.filter((i) => i.severity === "block");
      const pricing = blocking.find((i) => i.where.includes("Pricing"));
      if (pricing !== undefined && blocking.length === 1) {
        return "Not saved — pick a pricing plan (or set a price) and it will be written";
      }
      const count = blocking.length;
      return `Not saved — ${count} ${count === 1 ? "problem" : "problems"} above have to be fixed first`;
    }
    case "saving":
      return "Saving…";
    case "saved":
      return (
        <>
          {/* The path, because this editor writes a file the user also edits by
              hand and runs the CLI against -- knowing which one is the point. */}
          <span className="page-head__path">listings/{name}/listing.yaml</span>
          {" · "}
          Autosaved
        </>
      );
  }
}
