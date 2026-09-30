import type { ReactNode } from "react";
import type { SaveState } from "../../hooks/useAutosave";
import { SavedChip } from "./SavedChip";

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
 * file has not been written.
 *
 * A listing template's editor says the same about its own file (UI doc §1,
 * §3). Its `unsaved` is the common case rather than the rare one -- A36
 * writes only complete templates -- and the sentence already fits it. */
export function metaFor(
  save: SaveState,
  name: string | null,
  subject: "listing" | "listing-template" = "listing",
): ReactNode {
  const template = subject === "listing-template";
  switch (save.kind) {
    case "unnamed":
      return template
        ? "Not saved — name this template to save it"
        : "Not saved — double-click the name above to name this listing";
    case "name-taken":
      return `There is already a ${template ? "listing template" : "listing"} called “${save.name}” — pick another name`;
    case "save-failed":
      return "Couldn't save — the edit is kept locally and retries on your next change";
    case "unsaved":
      return "Not saved — fix the highlighted field and it will be written";
    case "saving":
      return "Saving…";
    case "saved":
      // The path, because this editor writes a file the user also edits by
      // hand and runs the CLI against -- one click away, in the chip's card.
      return (
        <SavedChip
          path={
            template ? `listing-templates/${name}/template.yaml` : `listings/${name}/listing.yaml`
          }
          savedAt={save.savedAt}
          subject={subject}
        />
      );
  }
}
