import { useEffect, useState, useSyncExternalStore } from "react";
import { createListing, describeListingDraft, patchListing, renameListing } from "../api/listings";
import { listingDocument } from "../pages/editor/listingDocument";
import type { ListingDetail } from "../types";
import { type AutosaveTransport, ListingAutosave, type SaveState } from "./listingAutosave";

/** A listing: `POST /api/listing-draft`, `POST /api/listings`, a PATCH of
 * the delta and the rename. A refused create answers the *empty* draft
 * beside its field errors, so only the errors are news. */
export const LISTING_TRANSPORT: AutosaveTransport = {
  document: (detail) => listingDocument(detail),
  describe: (candidate) => describeListingDraft(candidate),
  create: async (name, candidate) => {
    const fresh = await createListing({ name, document: candidate });
    if (fresh.name === "") return { saved: false, issues: null, field_errors: fresh.field_errors };
    return { saved: true, detail: fresh };
  },
  // A PATCH whose merged document contradicts itself answers 200 with
  // `field_errors` and the listing unchanged: not written, so not saved.
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

/**
 * {@link ListingAutosave} for a React editor: one per mount, on the name,
 * document and transport it mounted with, flushed on unmount so a listing
 * switch (or navigating away) never drops the last few hundred milliseconds of
 * typing. A listing switch remounts the editor while the next one loads.
 */
export function useAutosave(
  name: string | null,
  initial: ListingDetail,
  options: {
    onNamed?: (name: string, fresh: ListingDetail) => void;
    /** The listing's by default. */
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
