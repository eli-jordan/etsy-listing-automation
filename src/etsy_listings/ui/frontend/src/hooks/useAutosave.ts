import { useCallback, useEffect, useRef, useState } from "react";
import { createListing, describeListingDraft, patchListing, renameListing } from "../api/listings";
import { listingDocument } from "../pages/editor/listingDocument";
import type { ListingDetail } from "../types";

/** How long the editor waits after the last edit before saving -- long
 * enough that a run of keystrokes in a text field collapses into one
 * request, short enough that "Saved a moment ago" reads as true. Also
 * flushed immediately on blur, on a tab switch and on unmount
 * (see `flush` below), so a save is never waiting on this timer alone. */
export const AUTOSAVE_DEBOUNCE_MS = 800;

type Patch = Record<string, unknown>;

/** Where the listing stands with the disk, as the page head reports it.
 *
 * `unsaved` is the state where the listing has a name but the server would
 * not write the document: since PRD 70 that means the document contradicts
 * itself (a price in the wrong currency, a title over Etsy's limit), never
 * that it is merely incomplete. `field_errors` names the field; this says
 * the consequence is a file that does not exist. */
export type SaveState =
  | { kind: "unnamed" }
  | { kind: "saving" }
  | { kind: "saved"; savedAt: number }
  | { kind: "unsaved" }
  | { kind: "name-taken"; name: string }
  | { kind: "save-failed" };

/** A `{ kind: "saved" }` stamped with when. Successful writes use the browser
 * clock; the initial state can instead use `listing.yaml`'s mtime supplied by
 * the server. */
function saved(savedAt = Date.now()): SaveState {
  return { kind: "saved", savedAt };
}

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

/** `design:` as `config/listing.py`'s `_coerce_design` will store it.
 *
 * The editor sends the bare ref a human writes in `listing.yaml`, and the
 * server normalises it to `{default: ref}` -- so between the edit and the
 * response, local state held a *string* where every consumer expects the map,
 * and `Object.keys("../../designs/x.png")` made the design strip report "45
 * artworks". On a saved listing the response healed it 800ms later, which is
 * why it went unnoticed; on a draft there is no response to heal it.
 *
 * Applied to local state only. The patch itself keeps the bare form, because
 * that is the form the file stores. */
function coerceDesign(detail: Patch): Patch {
  if (typeof detail.design !== "string") return detail;
  return { ...detail, design: { default: detail.design } };
}

interface UseAutosave {
  /** The listing as the editor should render it: the server's last response,
   * with any not-yet-saved edits already merged in. */
  detail: ListingDetail;
  /** Applies a partial `listing.yaml` patch: updates local state immediately
   * and schedules (or extends) the debounced save. */
  update: (patch: Patch) => void;
  /** Shows a value the server has already written -- an AI run's drafted
   * brief (market-seo.md, *AI runs*) -- without saving it again: local
   * state only, nothing pending, the save state untouched. Sending it back
   * would be a second write of the same value, and would race the seller's
   * own next edit to that field. */
  adopt: (patch: Patch) => void;
  /** Sends whatever is pending right now, without waiting for the debounce.
   * Callers use this on blur and on a tab switch; the hook itself calls it on
   * unmount, and `rename` awaits it. */
  flush: () => Promise<void>;
  /** Names an unnamed listing (creating it) or renames one that exists. Both
   * end at the same place -- a listing on disk under a new name -- which is
   * why they are one function and one `onNamed` callback. */
  commitName: (next: string) => void;
  save: SaveState;
}

/**
 * Autosave for listings. The mockup-template calibrator shares the debounce
 * interval but has a simpler full-document transport.
 *
 * It holds three transports, not one, because the editor is also the create
 * form and a listing therefore passes through three states in one sitting:
 *
 * | on disk | named | sends |
 * |---|---|---|
 * | no | no | `POST /api/listing-draft` -- writes nothing, refreshes issues |
 * | no | yes | `POST /api/listings` -- writes it, if the document will validate |
 * | yes | -- | `PATCH /api/listings/{name}` -- the delta |
 *
 * They live together rather than in a page or a sibling hook because the
 * choice depends on what is in `pending`, and `pending` lives here: a second
 * hook would have to copy the debounce, the merge and the flush-on-unmount to
 * reach it, and the create/patch boundary would end up somewhere other than
 * the place that knows whether it is safe to send at all.
 */
export function useAutosave(
  name: string | null,
  initial: ListingDetail,
  options: { onNamed?: (name: string, fresh: ListingDetail) => void } = {},
): UseAutosave {
  const [detail, setDetail] = useState(initial);
  const [save, setSave] = useState<SaveState>(() =>
    name === null
      ? { kind: "unnamed" }
      : saved(initial.modified_at === null ? Date.now() : Date.parse(initial.modified_at)),
  );
  const pending = useRef<Patch | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** The name this listing is on disk under, or `null` while it is not. */
  const savedName = useRef<string | null>(name);
  /** A create or rename is in flight: edits keep accumulating in `pending`,
   * but nothing is sent, because the name they would be sent under is exactly
   * what is being decided. */
  const naming = useRef(false);
  /** A PATCH to the named listing is in flight. `update()` schedules a fresh
   * debounce on every edit, and `flush()` is also called directly on blur,
   * tab-switch and unmount -- any of those can land while the previous PATCH
   * is still outstanding. Without this guard, two PATCHes end up in flight
   * at once and whichever *resolves* last wins, regardless of which was
   * *sent* last. */
  const patching = useRef(false);
  /** A flush arrived while `patching.current` was true. Rather than firing a
   * second concurrent PATCH, it sets this so the in-flight one's `finally`
   * re-runs `flush()` once it settles -- picking up whatever is in `pending`
   * at that later point, one request at a time. */
  const patchAgain = useRef(false);
  /** A name typed for a listing that is not on disk yet. It outlives a refused
   * create, which is what lets the next edit retry it rather than asking the
   * user to type the name again. */
  const draftName = useRef("");
  /** What `adopt` has shown since the last save *sent* after it. A response
   * to a request sent earlier describes the file as it was before the server
   * wrote these values -- an AI run's brief lands while an autosave is in
   * flight -- so they are laid back over that response rather than blanked
   * by it. A new object on every adopt, so a request can tell whether one
   * happened while it was out. */
  const adopted = useRef<Patch | null>(null);
  // `detail` as the save callbacks should read it. A ref rather than a
  // dependency because a save must send what is on screen *now*, not what was
  // on screen when the debounce was armed.
  const latest = useRef(detail);
  const onNamed = options.onNamed;

  const clearTimer = useCallback(() => {
    if (timer.current !== null) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  }, []);

  /** Whatever the server should be told about right now: the last response
   * with every pending edit merged over it, as a `listing.yaml` document. */
  const candidate = useCallback((): Patch => {
    return mergePatch(listingDocument(latest.current) as Patch, pending.current ?? {});
  }, []);

  /** `sentWith` is `adopted` as it stood when the request was sent. */
  const applyResponse = useCallback((fresh: ListingDetail, sentWith: Patch | null) => {
    // A response carrying field errors describes the *empty* draft alongside
    // them (there is no listing to describe), so only the errors are news --
    // taking the rest would wipe the document being edited.
    if (Object.keys(fresh.field_errors ?? {}).length > 0) {
      setDetail((current) => ({ ...current, field_errors: fresh.field_errors }));
      return;
    }
    // Sent after the last adopt: the response already carries what was
    // adopted, and from here the file is the word on it.
    if (adopted.current === sentWith) adopted.current = null;
    // Keep edits made while a save was in flight visible, over anything
    // adopted meanwhile: the seller's own typing wins.
    const overlay = mergePatch(adopted.current ?? {}, pending.current ?? {});
    setDetail(
      Object.keys(overlay).length === 0
        ? fresh
        : (coerceDesign(mergePatch(fresh, overlay)) as ListingDetail),
    );
  }, []);

  const create = useCallback(
    async (next: string) => {
      setSave({ kind: "saving" });
      // What this create carries, captured before the await. An edit made
      // while it is in flight lands in a *different* `pending` object
      // (`update` replaces it rather than mutating), and that one is not in
      // the document being sent -- so clearing `pending` wholesale on success
      // would drop it silently. The same rule `applyResponse` already states
      // for a PATCH, applied to the one request that did not have it: PRD
      // 68's drafted brief is written by a request that resolves during
      // exactly this window, and it went missing every time.
      const sent = pending.current;
      const sentWith = adopted.current;
      const fresh = await createListing({ name: next, document: candidate() });
      if (fresh.name === "") {
        // The server would not write it -- `field_errors` says why. `pending`
        // stays put, and so does the name, so the edit that fixes the document
        // is what retries the create.
        applyResponse(fresh, sentWith);
        setSave({ kind: "unsaved" });
        return;
      }
      if (pending.current === sent) pending.current = null;
      savedName.current = next;
      applyResponse(fresh, sentWith);
      // Left "saving" when something is still pending, so the flush
      // `commitName` schedules is what reports the listing saved -- the same
      // way `flush` withholds it while another edit is waiting.
      if (pending.current === null) setSave(saved());
      onNamed?.(next, fresh);
    },
    [applyResponse, candidate, onNamed],
  );

  const flush = useCallback(async (): Promise<void> => {
    clearTimer();
    if (naming.current) return;

    if (savedName.current !== null) {
      if (patching.current) {
        // A PATCH is already in flight. Sending a second one now would race
        // it -- whichever *resolves* last would win, not whichever holds the
        // newer edit. Defer instead: the loop below re-checks `pending` once
        // the in-flight one settles, rather than firing a concurrent request.
        patchAgain.current = true;
        return;
      }
      // A loop, not recursion, so a deferred continuation (below) can pick up
      // whatever landed in `pending` while the previous PATCH was in flight,
      // one request at a time, without the function calling itself. The React
      // compiler cannot memoize a `useCallback` that calls itself.
      for (;;) {
        const patch = pending.current;
        const currentName = savedName.current;
        if (patch === null || currentName === null) return;
        // Cleared only once the PATCH actually lands -- a rejection (dropped
        // connection, a 5xx) must leave the edit right where the next flush
        // (the next debounce, or the next `update()`, which merges onto
        // whatever is still here) will find and retry it. Losing it here
        // would silently discard whatever was pending, structured
        // `description` triples included (AI SEO implementation plan, PR6).
        pending.current = null;
        patching.current = true;
        setSave({ kind: "saving" });
        const sentWith = adopted.current;
        try {
          const fresh = await patchListing(currentName, patch);
          applyResponse(fresh, sentWith);
          // A newer edit may already be waiting. Marking this one saved would
          // hide it until the next iteration starts.
          if (pending.current === null) setSave(saved());
        } catch {
          // Swallowed, not rethrown: nothing that calls `flush()` (the
          // debounce timer, `onBlur`, unmount) is set up to catch it, and a
          // failed autosave is reported through `save` -- the same channel
          // every other outcome here uses -- rather than an exception a
          // caller would have to remember to handle.
          pending.current = mergePatch(patch, pending.current ?? {});
          setSave({ kind: "save-failed" });
        } finally {
          patching.current = false;
        }
        if (!patchAgain.current) return;
        patchAgain.current = false;
      }
    }

    if (pending.current === null) return;

    // Named, but refused once already: every edit is another attempt at the
    // document the server would not write, so it retries rather than settling
    // for a description of it.
    if (draftName.current !== "") {
      naming.current = true;
      try {
        await create(draftName.current);
      } catch {
        setSave({ kind: "name-taken", name: draftName.current });
      } finally {
        naming.current = false;
      }
      return;
    }

    // Not on disk and not named: describe the candidate so the issues banner
    // stays true. Nothing is written, so `pending` is not cleared -- it is what
    // the create will carry once a name arrives.
    const sentWith = adopted.current;
    const fresh = await describeListingDraft(candidate());
    applyResponse(fresh, sentWith);
  }, [applyResponse, candidate, clearTimer, create]);

  const update = useCallback(
    (patch: Patch) => {
      setDetail((current) => coerceDesign(mergePatch(current, patch)) as ListingDetail);
      pending.current = mergePatch(pending.current ?? {}, patch);
      clearTimer();
      timer.current = setTimeout(() => void flush(), AUTOSAVE_DEBOUNCE_MS);
    },
    [clearTimer, flush],
  );

  const adopt = useCallback((patch: Patch) => {
    adopted.current = mergePatch(adopted.current ?? {}, patch);
    setDetail((current) => coerceDesign(mergePatch(current, patch)) as ListingDetail);
  }, []);

  const commitName = useCallback(
    (next: string) => {
      if (next === savedName.current || naming.current) return;
      clearTimer();
      naming.current = true;
      setSave({ kind: "saving" });
      const run = async () => {
        if (savedName.current === null) {
          draftName.current = next;
          await create(next);
          return;
        }
        // Drain first: the old name still exists, so an edit already made has
        // somewhere to go. Anything typed from here lands in `pending` and is
        // sent under the new name -- two fates, and no third.
        const patch = pending.current;
        pending.current = null;
        const sentWith = adopted.current;
        if (patch !== null) applyResponse(await patchListing(savedName.current, patch), sentWith);
        const fresh = await renameListing(savedName.current, next);
        savedName.current = next;
        // Read from the file after the drain, under the rename's lock: it
        // carries anything adopted before it.
        if (adopted.current === sentWith) adopted.current = null;
        setDetail(fresh);
        setSave(saved());
        onNamed?.(next, fresh);
      };
      run()
        .catch(() => setSave({ kind: "name-taken", name: next }))
        .finally(() => {
          naming.current = false;
          if (pending.current !== null) {
            timer.current = setTimeout(() => void flush(), AUTOSAVE_DEBOUNCE_MS);
          }
        });
    },
    [applyResponse, clearTimer, create, flush, onNamed],
  );

  useEffect(() => {
    latest.current = detail;
  }, [detail]);

  // Flush on unmount so a listing switch (or navigating away) never silently
  // drops the last few hundred milliseconds of typing.
  useEffect(() => () => void flush(), [flush]);

  return { detail, update, adopt, flush, commitName, save };
}
