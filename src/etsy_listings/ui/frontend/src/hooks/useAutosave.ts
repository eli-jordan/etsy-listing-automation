import { useCallback, useEffect, useRef, useState } from "react";
import { patchListing } from "../api/listings";
import type { ListingDetail } from "../types";

/** How long the editor waits after the last edit before PATCHing -- long
 * enough that a run of keystrokes in a text field collapses into one
 * request, short enough that the "Autosaved just now" caption reads as
 * true. Also flushed immediately on blur, on a tab switch and on unmount
 * (see `flush` below), so a save is never waiting on this timer alone. */
export const AUTOSAVE_DEBOUNCE_MS = 800;

type Patch = Record<string, unknown>;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The same one-level-deep merge `ui/api/listings.py`'s `_merge` applies
 * server-side, mirrored here so the optimistic local state -- and the
 * accumulation of several edits made before the debounce fires -- agrees
 * with what the server will actually end up storing. */
function mergePatch(base: Patch, patch: Patch): Patch {
  const merged: Patch = { ...base };
  for (const [key, value] of Object.entries(patch)) {
    if (key === "etsy" && isPlainObject(value) && isPlainObject(merged.etsy)) {
      merged.etsy = { ...merged.etsy, ...value };
    } else {
      merged[key] = value;
    }
  }
  return merged;
}

interface UseAutosave {
  /** The listing as the editor should render it: the server's last response,
   * with any not-yet-saved edits already merged in. */
  detail: ListingDetail;
  /** Applies a partial `listing.yaml` patch: updates local state immediately
   * and schedules (or extends) the debounced PATCH. */
  update: (patch: Patch) => void;
  /** Sends whatever is pending right now, without waiting for the debounce.
   * A no-op when nothing is pending. Callers use this on blur and on a tab
   * switch; the hook itself calls it on unmount. */
  flush: () => void;
  saving: boolean;
}

/**
 * Autosave (phase 5): the first autosave precedent in this codebase (the
 * calibrator uses explicit Save/Reset). One hook per mounted listing --
 * `ListingEditorPage` remounts it (via `key`) rather than feeding it a new
 * `name`, so there is no listing-switch case to handle here.
 */
export function useAutosave(name: string, initial: ListingDetail): UseAutosave {
  const [detail, setDetail] = useState(initial);
  const [saving, setSaving] = useState(false);
  const pending = useRef<Patch | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flush = useCallback(() => {
    if (timer.current !== null) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    const patch = pending.current;
    if (patch === null) return;
    pending.current = null;
    setSaving(true);
    patchListing(name, patch)
      .then((fresh) => setDetail(fresh))
      .finally(() => setSaving(false));
  }, [name]);

  const update = useCallback(
    (patch: Patch) => {
      setDetail((current) => mergePatch(current, patch) as ListingDetail);
      pending.current = mergePatch(pending.current ?? {}, patch);
      if (timer.current !== null) clearTimeout(timer.current);
      timer.current = setTimeout(flush, AUTOSAVE_DEBOUNCE_MS);
    },
    [flush],
  );

  // Flush on unmount so a listing switch (or navigating away) never silently
  // drops the last few hundred milliseconds of typing.
  useEffect(() => () => flush(), [flush]);

  return { detail, update, flush, saving };
}
