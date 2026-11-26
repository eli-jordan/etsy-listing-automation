import { useEffect, useState, useSyncExternalStore } from "react";
import { createListing, describeListingDraft, patchListing, renameListing } from "../api/listings";
import { listingDocument } from "../pages/editor/listingDocument";
import type { ListingDetail } from "../types";
import { type AutosaveTransport, ListingAutosave, type SaveState } from "./listingAutosave";

export const LISTING_TRANSPORT: AutosaveTransport = {
  document: (detail) => listingDocument(detail),
  describe: (candidate) => describeListingDraft(candidate),
  create: async (name, candidate) => {
    const fresh = await createListing({ name, document: candidate });
    if (fresh.name === "") return { saved: false, issues: null, field_errors: fresh.field_errors };
    return { saved: true, detail: fresh };
  },
  save: async (name, patch) => {
    const fresh = await patchListing(name, patch);
    if (Object.keys(fresh.field_errors ?? {}).length > 0) {
      return { saved: false, issues: null, field_errors: fresh.field_errors };
    }
    return { saved: true, detail: fresh };
  },
  rename: (from, to) => renameListing(from, to),
};

interface UseAutosave extends Pick<ListingAutosave, "update" | "adopt" | "flush" | "commitName"> {
  detail: ListingDetail;
  save: SaveState;
}

export function useAutosave(
  name: string | null,
  initial: ListingDetail,
  options: {
    onNamed?: (name: string, fresh: ListingDetail) => void;
    transport?: AutosaveTransport;
  } = {},
): UseAutosave {
  const [autosave] = useState(
    () => new ListingAutosave(name, initial, options.transport ?? LISTING_TRANSPORT),
  );
  const { detail, save } = useSyncExternalStore(autosave.subscribe, autosave.snapshot);
  const { onNamed } = options;

  useEffect(() => autosave.connect(onNamed), [autosave, onNamed]);
  useEffect(() => () => void autosave.flush(), [autosave]);

  return {
    detail,
    save,
    update: autosave.update,
    adopt: autosave.adopt,
    flush: autosave.flush,
    commitName: autosave.commitName,
  };
}
