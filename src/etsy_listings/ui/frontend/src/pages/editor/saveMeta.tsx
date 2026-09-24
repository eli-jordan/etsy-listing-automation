import type { ReactNode } from "react";
import type { SaveState } from "../../hooks/useAutosave";
import { SavedAgo } from "./SavedAgo";

/** What the editor's page head says about where this listing stands with the
 * disk.
 *
 * Its own module, and pure, so the five states can be read (and tested) as five
 * sentences rather than five renders.
 *
 * The "not saved yet" ones say what is in the way rather than a bland "Not
 * saved". Since PRD 70 that is a much rarer state: naming a listing writes it,
 * and incompleteness never withholds the file. What is left is a document the
 * server will not write because it contradicts itself -- and `field_errors`
 * has already said which field, inline, so this line only has to say that the
 * file has not been written. */
export function metaFor(save: SaveState, name: string | null): ReactNode {
  switch (save.kind) {
    case "unnamed":
      return "Not saved — double-click the name above to name this listing";
    case "name-taken":
      return `There is already a listing called “${save.name}” — pick another name`;
    case "save-failed":
      return "Couldn't save — the edit is kept locally and retries on your next change";
    case "unsaved":
      return "Not saved — fix the highlighted field and it will be written";
    case "saving":
      return "Saving…";
    case "saved":
      return (
        <>
          {/* The path, because this editor writes a file the user also edits by
              hand and runs the CLI against -- knowing which one is the point. */}
          <span className="page-head__path">listings/{name}/listing.yaml</span>
          {" · "}
          <span className="page-head__saved">
            <span className="page-head__dot" aria-hidden="true" />
            <SavedAgo savedAt={save.savedAt} />
          </span>
        </>
      );
  }
}
