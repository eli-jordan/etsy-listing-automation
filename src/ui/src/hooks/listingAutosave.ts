import type { Issue, ListingDetail } from "../types";
import { type Clock, type Settled, WRITTEN, WriteLoop } from "./writeLoop";

export type Patch = Record<string, unknown>;

/** Where the listing stands with the disk, as the page head reports it.
 *
 * `unsaved` is the state where the listing has a name but the server would
 * not write the document: since ADR-0043 that means the document contradicts
 * itself (a price in the wrong currency, a title over Etsy's limit), never
 * that it is merely incomplete. `field_errors` names the field; this says
 * the consequence is a file that does not exist.
 *
 * A new object each time a save lands, so an observer can tell two saves
 * apart even when `modified_at` does not move. */
export type SaveState =
  | { kind: "unnamed" }
  | { kind: "saving" }
  | { kind: "saved"; savedAt: number }
  | { kind: "unsaved"; reason?: string }
  | { kind: "name-taken"; name: string }
  | { kind: "save-failed" };

/** What one write came to. `saved: false` is a document the server would
 * not write -- nothing on disk changed -- carrying what to show about why:
 * the field errors, and the issues where they describe the candidate (a
 * listing template's valid-only save, template completeness) rather than something else. */
export type SaveOutcome =
  | { saved: true; detail: ListingDetail }
  | { saved: false; issues: Issue[] | null; field_errors: Record<string, string> };

/** How a document reaches the disk. The editor's three states (see
 * {@link ListingAutosave}) are the same for a listing and a listing template;
 * what differs is the endpoints and the document, so that is what a
 * transport supplies. `describe` is `null` where an unnamed draft has
 * nothing to ask the server. */
export interface AutosaveTransport {
  /** The stored document, out of what the editor shows. */
  document: (detail: ListingDetail) => Patch;
  describe: ((candidate: Patch) => Promise<ListingDetail>) | null;
  create: (name: string, candidate: Patch) => Promise<SaveOutcome>;
  /** `patch` is the edits since the last save; `candidate` the whole
   * document with them applied. A transport sends whichever it writes. */
  save: (name: string, patch: Patch, candidate: Patch) => Promise<SaveOutcome>;
  rename: (from: string, to: string) => Promise<ListingDetail>;
}

/** What {@link ListingAutosave} shows. */
export interface AutosaveView {
  /** The server's last response, with any not-yet-saved edits merged in. */
  detail: ListingDetail;
  save: SaveState;
}

const SAVING: SaveState = { kind: "saving" };

/** An unnamed draft has no file for an edit to be in. */
const NOT_ON_DISK: Settled = { written: false, message: "This listing has no name yet" };

/** A `{ kind: "saved" }` stamped with when. Successful writes use the browser
 * clock; the initial state can instead use `listing.yaml`'s mtime supplied by
 * the server. */
function saved(savedAt = Date.now()): SaveState {
  return { kind: "saved", savedAt };
}

/** Where a listing's save state starts: unnamed, or saved at its file's
 * mtime (now, when the server has none). */
function initialSave(name: string | null, modifiedAt: string | null): SaveState {
  if (name === null) return { kind: "unnamed" };
  return saved(modifiedAt === null ? Date.now() : Date.parse(modifiedAt));
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The same one-level-deep merge `core/application/listing_edits.py`'s `_merge` applies
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
 * and `Object.keys("designs/x.png")` made the design strip report "45
 * artworks". On a saved listing the response healed it 800ms later, which is
 * why it went unnoticed; on a draft there is no response to heal it.
 *
 * Applied to local state only. The patch itself keeps the bare form, because
 * that is the form the file stores. */
function coerceDesign(detail: Patch): Patch {
  if (typeof detail.design !== "string") return detail;
  return { ...detail, design: { default: detail.design } };
}

function refusalMessage(fieldErrors: Record<string, string>): string {
  return (
    fieldErrors.__root__ ??
    Object.values(fieldErrors)[0] ??
    "The server would not write this document"
  );
}

/**
 * A listing's document in the editor, and how it gets to disk. The listing
 * template editor uses it too, through its own transport. Order, debounce and
 * what happens to an unwritten edit are the {@link WriteLoop}'s; this adds the
 * editor's three states, because the editor is also the create form and a
 * listing passes through all three in one sitting:
 *
 * | on disk | named | sends |
 * |---|---|---|
 * | no | no | `POST /api/listing-draft` -- writes nothing, refreshes issues |
 * | no | yes | `POST /api/listings` -- writes it, if the document will validate |
 * | yes | -- | `PATCH /api/listings/{name}` -- the delta |
 *
 * The state is chosen when a write goes rather than when the edit is made, so
 * an edit made while a create or rename is out goes under the name it settled
 * on: the name is exactly what that request is deciding.
 *
 * Outside React, so a save reads what is on screen now rather than what a
 * render closed over, and an edit arriving after the editor unmounted (a
 * flush on the way out, a nudge saved as its tab closes) is still sent.
 */
export class ListingAutosave {
  private view: AutosaveView;
  private listeners = new Set<() => void>();
  /** The name this listing is on disk under, or `null` while it is not. */
  private name: string | null;
  /** A name typed for a listing that is not on disk yet. It outlives a refused
   * create, which is what lets the next edit retry it rather than asking the
   * user to type the name again. */
  private draftName = "";
  private naming = false;
  /** What `adopt` has shown since the last save *sent* after it. A response
   * to a request sent earlier describes the file as it was before the server
   * wrote these values -- an AI run's brief lands while an autosave is in
   * flight -- so they are laid back over that response rather than blanked
   * by it. A new object on every adopt, so a request can tell whether one
   * happened while it was out. */
  private adopted: Patch | null = null;
  private onNamed: ((name: string, fresh: ListingDetail) => void) | undefined = undefined;
  private readonly transport: AutosaveTransport;
  private readonly loop: WriteLoop<Patch>;

  constructor(
    name: string | null,
    initial: ListingDetail,
    transport: AutosaveTransport,
    clock?: Clock,
  ) {
    this.name = name;
    this.transport = transport;
    this.view = { detail: initial, save: initialSave(name, initial.modified_at) };
    this.loop = new WriteLoop<Patch>({
      send: (patch) => this.send(patch),
      merge: mergePatch,
      failed: (error) => this.failed(error),
      ...(clock === undefined ? {} : { clock }),
    });
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => void this.listeners.delete(listener);
  };

  snapshot = () => this.view;

  connect(onNamed: ((name: string, fresh: ListingDetail) => void) | undefined) {
    this.onNamed = onNamed;
  }

  /** Applies a partial `listing.yaml` patch: shows it at once and schedules
   * (or extends) the debounced save. */
  update = (patch: Patch) => {
    this.show({ detail: this.merged(patch) });
    this.loop.edit(patch);
  };

  /** Shows a value the server has already written -- an AI run's drafted
   * brief (features/market-seo-20260924/spec.md, *AI runs*) -- without saving it again: local
   * state only, nothing pending, the save state untouched. Sending it back
   * would be a second write of the same value, and would race the seller's
   * own next edit to that field. */
  adopt = (patch: Patch) => {
    this.adopted = mergePatch(this.adopted ?? {}, patch);
    this.show({ detail: this.merged(patch) });
  };

  /** Sends whatever is pending right now, without waiting for the debounce,
   * and answers once no write is out. A caller about to act on the file reads
   * the answer: it is what says the file holds what is on screen. */
  flush = async (): Promise<Settled> => {
    const settled = await this.loop.flush();
    return settled.written && this.name === null ? NOT_ON_DISK : settled;
  };

  /** Names an unnamed listing (creating it) or renames one that exists. Both
   * end at the same place -- a listing on disk under a new name -- which is
   * why they are one function and one `onNamed` callback. */
  commitName = (next: string) => {
    if (next === this.name || this.naming) return;
    this.naming = true;
    this.show({ save: SAVING });
    const named = this.name === null ? this.create(next) : this.moveTo(next);
    void named.then(() => {
      this.naming = false;
    });
  };

  private create(next: string): Promise<Settled> {
    this.draftName = next;
    // Nothing to carry is still a write owed: the create itself.
    this.loop.edit({});
    return this.loop.flush();
  }

  /** Drain first: the old name still exists, so an edit already made has
   * somewhere to go, and one it cannot write stops the rename rather than
   * reporting a saved listing without it. Anything typed from here is sent
   * under the new name -- two fates, and no third. */
  private moveTo(next: string): Promise<Settled> {
    return this.loop.afterWrite(async () => {
      const from = this.name;
      if (from === null) return;
      const sentWith = this.adopted;
      try {
        const fresh = await this.transport.rename(from, next);
        this.name = next;
        this.landed(fresh, sentWith);
        this.onNamed?.(next, fresh);
      } catch {
        this.show({ save: { kind: "name-taken", name: next } });
      }
    });
  }

  private send(patch: Patch): Promise<Settled> {
    if (this.name !== null) return this.save(this.name, patch);
    // Named, but refused once already: every edit is another attempt at the
    // document the server would not write, so it retries rather than settling
    // for a description of it.
    if (this.draftName !== "") return this.createNamed(this.draftName, patch);
    return this.describe(patch);
  }

  private async save(name: string, patch: Patch): Promise<Settled> {
    this.show({ save: SAVING });
    const sentWith = this.adopted;
    const outcome = await this.transport.save(name, patch, this.candidate(patch));
    if (!outcome.saved) return this.refused(outcome);
    this.landed(outcome.detail, sentWith);
    return WRITTEN;
  }

  private async createNamed(next: string, patch: Patch): Promise<Settled> {
    this.show({ save: SAVING });
    const sentWith = this.adopted;
    const outcome = await this.transport.create(next, this.candidate(patch));
    if (!outcome.saved) return this.refused(outcome);
    this.name = next;
    this.landed(outcome.detail, sentWith);
    this.onNamed?.(next, outcome.detail);
    return WRITTEN;
  }

  /** Not on disk and not named: describes the candidate so the issues banner
   * stays true. Nothing is written, so the edit comes back to the loop -- it is
   * what the create will carry once a name arrives. */
  private async describe(patch: Patch): Promise<Settled> {
    if (this.transport.describe === null) return NOT_ON_DISK;
    const sentWith = this.adopted;
    const fresh = await this.transport.describe(this.candidate(patch));
    this.show({ detail: this.answered(fresh, sentWith, patch) });
    return NOT_ON_DISK;
  }

  /** The whole document with `patch` applied. */
  private candidate(patch: Patch): Patch {
    return mergePatch(this.transport.document(this.view.detail), patch);
  }

  /** `fresh` is on disk. Saved only when nothing is waiting: a newer edit
   * would be hidden until its own write began. */
  private landed(fresh: ListingDetail, sentWith: Patch | null) {
    const detail = this.answered(fresh, sentWith);
    this.show(this.loop.held === null ? { detail, save: saved() } : { detail });
  }

  /** `fresh` laid under whatever it cannot know about. `sentWith` is `adopted`
   * as it stood when the request was sent, and `unwritten` what that request
   * carried if it wrote nothing. */
  private answered(
    fresh: ListingDetail,
    sentWith: Patch | null,
    unwritten: Patch = {},
  ): ListingDetail {
    // A response carrying field errors describes the *empty* draft alongside
    // them (there is no listing to describe), so only the errors are news --
    // taking the rest would wipe the document being edited.
    if (Object.keys(fresh.field_errors ?? {}).length > 0) {
      return { ...this.view.detail, field_errors: fresh.field_errors };
    }
    // Sent after the last adopt: the response already carries what was
    // adopted, and from here the file is the word on it.
    if (this.adopted === sentWith) this.adopted = null;
    // Keep edits made while a save was in flight visible, over anything
    // adopted meanwhile: the seller's own typing wins.
    const overlay = mergePatch(mergePatch(this.adopted ?? {}, unwritten), this.loop.held ?? {});
    if (Object.keys(overlay).length === 0) return fresh;
    return coerceDesign(mergePatch(fresh, overlay)) as ListingDetail;
  }

  /** A write the server refused: the edits stay on screen, and so does
   * everything else, with what the refusal said about them laid over. */
  private refused(outcome: SaveOutcome & { saved: false }): Settled {
    // A contradiction no single field owns has no field to highlight, so
    // the page head is the only place left to say what it is.
    const reason = outcome.field_errors.__root__;
    this.show({
      detail: {
        ...this.view.detail,
        field_errors: outcome.field_errors,
        ...(outcome.issues === null ? {} : { issues: outcome.issues }),
      },
      save: reason === undefined ? { kind: "unsaved" } : { kind: "unsaved", reason },
    });
    return { written: false, message: refusalMessage(outcome.field_errors) };
  }

  /** A request that rejected, reported through `save` as every other outcome
   * is. A draft being described has nothing to report: nothing was to be
   * written, so the banner keeps what it last knew until the next edit. */
  private failed(error: unknown): string {
    if (this.name !== null) this.show({ save: { kind: "save-failed" } });
    else if (this.draftName !== "") {
      this.show({ save: { kind: "name-taken", name: this.draftName } });
    }
    return error instanceof Error ? error.message : "Save failed";
  }

  private merged(patch: Patch): ListingDetail {
    return coerceDesign(mergePatch(this.view.detail, patch)) as ListingDetail;
  }

  private show(next: Partial<AutosaveView>) {
    this.view = { ...this.view, ...next };
    for (const listener of this.listeners) listener();
  }
}
