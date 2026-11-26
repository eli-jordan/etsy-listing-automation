import type { Issue, ListingDetail } from "../types";
import { type Clock, type Settled, WRITTEN, WriteLoop } from "./writeLoop";

export type Patch = Record<string, unknown>;

/** A new object each time a save lands, so an observer can tell two saves
 * apart even when `modified_at` does not move. */
export type SaveState =
  | { kind: "unnamed" }
  | { kind: "saving" }
  | { kind: "saved"; savedAt: number }
  | { kind: "unsaved"; reason?: string }
  | { kind: "name-taken"; name: string }
  | { kind: "save-failed" };

/** `saved: false`: the server wrote nothing, and says why. */
export type SaveOutcome =
  | { saved: true; detail: ListingDetail }
  | { saved: false; issues: Issue[] | null; field_errors: Record<string, string> };

export interface AutosaveTransport {
  /** The stored document, out of what the editor shows. */
  document: (detail: ListingDetail) => Patch;
  describe: ((candidate: Patch) => Promise<ListingDetail>) | null;
  create: (name: string, candidate: Patch) => Promise<SaveOutcome>;
  /** `patch`: the edits since the last save; `candidate`: the whole document with them. */
  save: (name: string, patch: Patch, candidate: Patch) => Promise<SaveOutcome>;
  rename: (from: string, to: string) => Promise<ListingDetail>;
}

export interface AutosaveView {
  detail: ListingDetail;
  save: SaveState;
}

const SAVING: SaveState = { kind: "saving" };

const NOT_ON_DISK: Settled = { written: false, message: "This listing has no name yet" };

function saved(savedAt = Date.now()): SaveState {
  return { kind: "saved", savedAt };
}

function initialSave(name: string | null, modifiedAt: string | null): SaveState {
  if (name === null) return { kind: "unnamed" };
  return saved(modifiedAt === null ? Date.now() : Date.parse(modifiedAt));
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

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

/** `design:` as `core/config/listing.py`'s `_coerce_design` will store it.
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

/** The field error no single field owns. */
export const ROOT_FIELD_ERROR = "__root__";

/** A write that carries nothing but the create itself. */
const CREATE_ONLY: Patch = {};

function refusalMessage(fieldErrors: Record<string, string>): string {
  return (
    fieldErrors[ROOT_FIELD_ERROR] ??
    Object.values(fieldErrors)[0] ??
    "The server would not write this document"
  );
}

export class ListingAutosave {
  private view: AutosaveView;
  private listeners = new Set<() => void>();
  private name: string | null;
  private draftName = "";
  private naming = false;
  private adoptedSinceLastSend: Patch | null = null;
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

  update = (patch: Patch) => {
    this.show({ detail: this.merged(patch) });
    this.loop.edit(patch);
  };

  /** Shows a value the server has already written, without saving it again. */
  adopt = (patch: Patch) => {
    this.adoptedSinceLastSend = mergePatch(this.adoptedSinceLastSend ?? {}, patch);
    this.show({ detail: this.merged(patch) });
  };

  flush = async (): Promise<Settled> => {
    const settled = await this.loop.flush();
    return settled.written && this.name === null ? NOT_ON_DISK : settled;
  };

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
    this.loop.edit(CREATE_ONLY);
    return this.loop.flush();
  }

  private moveTo(next: string): Promise<Settled> {
    return this.loop.afterWrite(async () => {
      const from = this.name;
      if (from === null) return;
      const adoptedWhenSent = this.adoptedSinceLastSend;
      try {
        const fresh = await this.transport.rename(from, next);
        this.name = next;
        this.landed(fresh, adoptedWhenSent);
        this.onNamed?.(next, fresh);
      } catch {
        this.show({ save: { kind: "name-taken", name: next } });
      }
    });
  }

  private send(patch: Patch): Promise<Settled> {
    if (this.name !== null) return this.save(this.name, patch);
    if (this.draftName !== "") return this.createNamed(this.draftName, patch);
    return this.describe(patch);
  }

  private async save(name: string, patch: Patch): Promise<Settled> {
    this.show({ save: SAVING });
    const adoptedWhenSent = this.adoptedSinceLastSend;
    const outcome = await this.transport.save(name, patch, this.candidate(patch));
    if (!outcome.saved) return this.refused(outcome);
    this.landed(outcome.detail, adoptedWhenSent);
    return WRITTEN;
  }

  private async createNamed(next: string, patch: Patch): Promise<Settled> {
    this.show({ save: SAVING });
    const adoptedWhenSent = this.adoptedSinceLastSend;
    const outcome = await this.transport.create(next, this.candidate(patch));
    if (!outcome.saved) return this.refused(outcome);
    this.name = next;
    this.landed(outcome.detail, adoptedWhenSent);
    this.onNamed?.(next, outcome.detail);
    return WRITTEN;
  }

  private async describe(patch: Patch): Promise<Settled> {
    if (this.transport.describe === null) return NOT_ON_DISK;
    const adoptedWhenSent = this.adoptedSinceLastSend;
    const fresh = await this.transport.describe(this.candidate(patch));
    this.show({ detail: this.answered(fresh, adoptedWhenSent, patch) });
    return NOT_ON_DISK;
  }

  private candidate(patch: Patch): Patch {
    return mergePatch(this.transport.document(this.view.detail), patch);
  }

  private landed(fresh: ListingDetail, adoptedWhenSent: Patch | null) {
    const detail = this.answered(fresh, adoptedWhenSent);
    this.show(this.loop.held === null ? { detail, save: saved() } : { detail });
  }

  private answered(
    fresh: ListingDetail,
    adoptedWhenSent: Patch | null,
    unwrittenPatch: Patch = {},
  ): ListingDetail {
    // A response carrying field errors describes the *empty* draft alongside
    // them (there is no listing to describe), so only the errors are news --
    // taking the rest would wipe the document being edited.
    if (Object.keys(fresh.field_errors ?? {}).length > 0) {
      return { ...this.view.detail, field_errors: fresh.field_errors };
    }
    if (this.adoptedSinceLastSend === adoptedWhenSent) this.adoptedSinceLastSend = null;
    const overlay = mergePatch(
      mergePatch(this.adoptedSinceLastSend ?? {}, unwrittenPatch),
      this.loop.held ?? {},
    );
    if (Object.keys(overlay).length === 0) return fresh;
    return coerceDesign(mergePatch(fresh, overlay)) as ListingDetail;
  }

  private refused(outcome: SaveOutcome & { saved: false }): Settled {
    // With no field to highlight, the page head is the only place left to
    // say what it is.
    const reason = outcome.field_errors[ROOT_FIELD_ERROR];
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
