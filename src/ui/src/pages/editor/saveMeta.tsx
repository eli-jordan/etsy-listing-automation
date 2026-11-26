import type { ReactNode } from "react";
import type { SaveState } from "../../hooks/listingAutosave";
import { SavedChip } from "./SavedChip";

export function metaFor(
  save: SaveState,
  name: string | null,
  subject: "listing" | "listing-template" = "listing",
  phone = false,
): ReactNode {
  const template = subject === "listing-template";
  switch (save.kind) {
    case "unnamed":
      return unnamed(template, phone);
    case "name-taken":
      return `There is already a ${template ? "listing template" : "listing"} called “${save.name}” — pick another name`;
    case "save-failed":
      return "Couldn't save — the edit is kept locally and retries on your next change";
    case "unsaved":
      return save.reason === undefined
        ? "Not saved — fix the highlighted field and it will be written"
        : `Not saved — ${save.reason}`;
    case "saving":
      return "Saving…";
    case "saved":
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

function unnamed(template: boolean, phone: boolean): string {
  if (template) return "Not saved — name this template to save it";
  const gesture = phone ? "tap" : "double-click";
  return `Not saved — ${gesture} the name above to name this listing`;
}
