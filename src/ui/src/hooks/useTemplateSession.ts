import { useEffect, useState, useSyncExternalStore } from "react";
import { getTemplateConfig, saveTemplateConfig, TemplateConflictError } from "../api/calibrator";
import {
  cancelPreparation,
  getPreparation,
  prepareTemplate,
  type MaskEdit,
  type MaskOperation,
  type Preparation,
} from "../api/preparation";
import type { TemplateConfigState } from "../types";
import { WriteLoop, WRITTEN, type Settled } from "./writeLoop";
import { usePreparation } from "./usePreparation";

/** Where the open template stands with the disk, as the header reports it.
 *
 * `conflict` is a save the server refused because template.yaml moved on
 * since this session read it (409/412). Unlike `failed`, retrying cannot fix
 * it: only {@link TemplateSession.reload} can. */
export type TemplateSaveState =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved"; savedAt: number }
  | { kind: "failed"; message: string }
  | { kind: "conflict"; message: string };

/** `none` while no template is selected. `ready` with a `null` config is a
 * folder of photos with no template.yaml yet -- the kind picker's case. */
export type TemplateLoad = "none" | "loading" | "ready" | "error";

export type PreparationAction = "prepare" | "prepare_again" | "retry";

export interface TemplateSession {
  load: TemplateLoad;
  /** The draft: the document as last read or saved, with every edit since. */
  config: TemplateConfigState | null;
  /** The document as this session last read or wrote it. */
  saved: TemplateConfigState | null;
  dirty: boolean;
  save: TemplateSaveState;
  /** Mask strokes drawn but not yet committed by a save. */
  maskEdits: MaskEdit[];
  /** The revision a preview's `calibration_revision` names: the one this
   * session last read or wrote, or the one its own preparation completed at.
   * A save that changed only labels leaves it where it is: nothing a preview
   * draws moved, so asking for the frame again would be wasted work. */
  calibrationRevision: string;
  /** The labels `calibrationRevision` was saved with, which a preview sends so
   * the server can recognise that revision behind later label saves. */
  calibrationLabels: string[];
  /** The revisions label-only saves have moved the document to since
   * `calibrationRevision`. Preparation reporting one of them is up to date. */
  relabelledRevisions: string[];
  preparation: Preparation | null;
  preparationError: string;
  /** An explicit prepare or cancel request is outstanding. */
  preparing: boolean;
  /** Replaces the draft and (re)arms the debounced autosave. */
  update: (config: TemplateConfigState) => void;
  setMaskEdits: (edits: MaskEdit[]) => void;
  /** The Marigold editor's composite is in flight. A Marigold draft's
   * autosave and the preparation reads both wait for it, so neither competes
   * with the frame the seller is looking at; a save that fell due meanwhile
   * goes the moment it lands. */
  setPreviewPending: (pending: boolean) => void;
  /** Saves now, without waiting for the debounce. Never rejects: the outcome
   * is in `save`, and in what it answers for a caller about to act on the
   * file. */
  flush: () => Promise<Settled>;
  /** Writes the draft even when nothing changed. Approving from the Preview
   * tab is a save: calibration status is derived from template.yaml, so the
   * observable act of approving is the file being written. */
  approve: () => Promise<Settled>;
  /** Discards the draft and mask edits and reads template.yaml again -- after
   * a conflict, or once a kind has been assigned. */
  reload: () => void;
  /** Saves anything pending, then queues preparation against the revision
   * the server now holds. `resetMasksForPhoto` drops the mask edits of
   * placements whose photo changed (their masks are what is being reset). */
  prepare: (action?: PreparationAction, resetMasksForPhoto?: boolean) => Promise<void>;
  cancelPreparation: () => Promise<void>;
  reloadPreparation: () => void;
}

/** Key-order-blind equality. The server answers with its own key order, so a
 * byte comparison would call an untouched document edited. */
function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value !== null && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonical(item)]),
    );
  return value;
}

function sameConfig(left: TemplateConfigState, right: TemplateConfigState): boolean {
  return JSON.stringify(canonical(left)) === JSON.stringify(canonical(right));
}

function sameLabels(left: TemplateConfigState, right: TemplateConfigState): boolean {
  return JSON.stringify(left.labels) === JSON.stringify(right.labels);
}

/** Whether going from `before` to `after` changes labels and nothing else. */
function onlyLabelsDiffer(before: TemplateConfigState, after: TemplateConfigState): boolean {
  return !sameLabels(before, after) && sameConfig({ ...before, labels: after.labels }, after);
}

/** One opening of one template. A switch or a reload makes a new one, so a
 * response for an old one is recognised by identity -- no name or sequence
 * guards -- and a save still in flight for it finishes against it. */
interface Doc {
  name: string;
  load: "loading" | "ready" | "error";
  draft: TemplateConfigState | null;
  saved: TemplateConfigState | null;
  /** Sent as `If-Match`; advanced by every save and by an adopted baseline. */
  revision: string;
  fence: string;
  fenceLabels: string[];
  relabelled: string[];
  maskEdits: MaskEdit[];
  save: TemplateSaveState;
  previewPending: boolean;
  /** This opening's saves. The draft is what is sent, read when it goes, so
   * what the loop holds is only whether one is owed. */
  loop: WriteLoop<SaveWanted>;
  /** The debounce ran out while held by a pending preview. */
  due: boolean;
}

/** `always` writes the draft even if nothing changed: an approval. */
interface SaveWanted {
  always: boolean;
}

interface View {
  name: string | null;
  load: TemplateLoad;
  config: TemplateConfigState | null;
  saved: TemplateConfigState | null;
  dirty: boolean;
  save: TemplateSaveState;
  maskEdits: MaskEdit[];
  calibrationRevision: string;
  calibrationLabels: string[];
  relabelledRevisions: string[];
  previewPending: boolean;
  preparationVersion: number;
  preparing: boolean;
  actionError: string;
}

interface Connections {
  reloadPreparation: () => void;
  onCatalogChanged: ((select?: string) => void) | undefined;
}

const IDLE: TemplateSaveState = { kind: "idle" };
const SAVING: TemplateSaveState = { kind: "saving" };
const NO_EDITS: MaskEdit[] = [];
const NO_LABELS: string[] = [];

/** What a failed save says: a conflict asks for a reload, anything else is
 * a plain failure. */
function saveFailure(e: unknown): Extract<TemplateSaveState, { message: string }> {
  if (e instanceof TemplateConflictError) return { kind: "conflict", message: e.message };
  return { kind: "failed", message: e instanceof Error ? e.message : "Save failed" };
}

function isDirty(doc: Doc): boolean {
  return (
    doc.draft !== null &&
    doc.saved !== null &&
    (!sameConfig(doc.draft, doc.saved) || doc.maskEdits.length > 0)
  );
}

/** The save state to show. A label edit changes nothing on screen until it
 * saves, and a pending preview can hold that save for as long as it likes, so
 * the wait reads as saving from the edit on. A failure stays until the next
 * attempt, and a conflict until a reload. */
function shownSave(doc: Doc): TemplateSaveState {
  const waiting = doc.loop.armed || doc.due;
  const labelled = doc.draft !== null && doc.saved !== null && !sameLabels(doc.draft, doc.saved);
  const settled = doc.save.kind === "idle" || doc.save.kind === "saved";
  return waiting && labelled && settled ? SAVING : doc.save;
}

/** The session's state outside React, so the save loop reads what is true
 * now rather than what a render closed over. Every field is per instance:
 * two sessions (two tabs' worth, or two tests) share nothing. */
class Session {
  private doc: Doc | null = null;
  private listeners = new Set<() => void>();
  /** The saves of documents this session has left: a flush on switch can
   * still be in flight when the next template is read, and must land first. */
  private leaving: Promise<unknown> = Promise.resolve();
  /** Operations are objects shared by successive draft snapshots, so an
   * editor handing back a list built before a save landed would otherwise
   * send its strokes twice. */
  private committed = new WeakSet<MaskOperation>();
  /** Preparation jobs this session queued. Only their completion may move
   * the revision baseline: anyone else's is a change made elsewhere. */
  private own = new Set<string>();
  private preparation: Preparation | null = null;
  private version = 0;
  private preparing = false;
  private actionError = "";
  private connections: Connections = { reloadPreparation: () => {}, onCatalogChanged: undefined };
  private view: View = this.render();

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => void this.listeners.delete(listener);
  };

  snapshot = () => this.view;

  connect(connections: Connections) {
    this.connections = connections;
  }

  open(name: string | null) {
    if ((this.doc?.name ?? null) === name) return;
    if (this.doc) this.detach(this.doc);
    this.doc = name === null ? null : this.read(name);
    this.preparation = null;
    this.emit();
  }

  /** Unmount: whatever is pending goes now, as on a switch. */
  close() {
    if (this.doc) this.detach(this.doc);
  }

  observe(preparation: Preparation | null) {
    this.preparation = preparation;
    const job = preparation?.latest_job;
    const doc = this.doc;
    if (
      doc &&
      job?.phase === "completed" &&
      job.template === doc.name &&
      this.own.has(job.id) &&
      job.config_revision === preparation?.config_revision &&
      doc.fence !== job.config_revision
    ) {
      this.fence(doc, job.config_revision);
      this.emit();
    }
  }

  update = (config: TemplateConfigState) => {
    const doc = this.doc;
    if (doc?.load !== "ready") return;
    doc.draft = config;
    this.edited(doc);
  };

  setMaskEdits = (edits: MaskEdit[]) => {
    const doc = this.doc;
    if (doc?.load !== "ready") return;
    doc.maskEdits = this.uncommitted(edits);
    this.edited(doc);
  };

  setPreviewPending = (pending: boolean) => {
    const doc = this.doc;
    if (!doc || doc.previewPending === pending) return;
    doc.previewPending = pending;
    if (doc.due && !this.held(doc)) {
      doc.due = false;
      void doc.loop.flush();
    }
    this.emit();
  };

  flush = (): Promise<Settled> => {
    const doc = this.doc;
    if (!doc) return Promise.resolve(WRITTEN);
    doc.due = false;
    return doc.loop.flush();
  };

  approve = (): Promise<Settled> => {
    const doc = this.doc;
    if (!doc) return Promise.resolve(WRITTEN);
    doc.due = false;
    doc.loop.edit({ always: true });
    return doc.loop.flush();
  };

  reload = () => {
    const doc = this.doc;
    if (!doc) return;
    doc.loop.discard();
    this.leave(doc);
    this.doc = this.read(doc.name);
    this.emit();
  };

  prepare = async (action: PreparationAction = "prepare", resetMasksForPhoto = false) => {
    const doc = this.doc;
    if (!doc?.draft || this.preparing) return;
    this.preparing = true;
    this.actionError = "";
    this.emit();
    try {
      if (resetMasksForPhoto) {
        const stale = new Set(
          this.preparation?.placements
            .filter((p) => !p.mask_available && p.mask_reason?.toLowerCase().includes("photo"))
            .map((p) => p.placement_id),
        );
        doc.maskEdits = doc.maskEdits.filter((edit) => !stale.has(edit.placement_id ?? null));
        this.emit();
      }
      // Preparing an older revision than the one on screen would prepare the
      // wrong thing.
      const settled = await this.flush();
      if (!settled.written) {
        this.actionError = settled.message;
        return;
      }
      const current = await getPreparation(doc.name);
      const submitted = await prepareTemplate({
        template: doc.name,
        config_revision: current.config_revision,
        request_id: crypto.randomUUID(),
        action,
        reset_masks_for_photo: resetMasksForPhoto,
        ...(action === "retry" && current.latest_job
          ? { previous_job: current.latest_job.id }
          : {}),
      });
      this.own.add(submitted.id);
      this.connections.reloadPreparation();
      this.connections.onCatalogChanged?.();
    } catch (e) {
      this.actionError = e instanceof Error ? e.message : "Preparation could not start";
    } finally {
      this.preparing = false;
      this.emit();
    }
  };

  cancelPreparation = async () => {
    const job = this.preparation?.active_job;
    if (!job) return;
    this.preparing = true;
    this.emit();
    try {
      await cancelPreparation(job.id);
      this.connections.reloadPreparation();
    } catch (e) {
      this.actionError = e instanceof Error ? e.message : "Cancellation failed";
    } finally {
      this.preparing = false;
      this.emit();
    }
  };

  private read(name: string): Doc {
    const doc: Doc = {
      name,
      load: "loading",
      draft: null,
      saved: null,
      revision: "",
      fence: "",
      fenceLabels: NO_LABELS,
      relabelled: [],
      maskEdits: NO_EDITS,
      save: IDLE,
      previewPending: false,
      loop: new WriteLoop<SaveWanted>({
        send: (wanted) => this.send(doc, wanted.always),
        merge: (older, newer) => ({ always: older.always || newer.always }),
        failed: (e) => {
          const failure = saveFailure(e);
          doc.save = failure;
          this.emit();
          return failure.message;
        },
        due: () => {
          if (this.held(doc)) doc.due = true;
          else void doc.loop.flush();
        },
      }),
      due: false,
    };
    // After any save still in flight, or the read could describe the file
    // from before it.
    void this.leaving
      .then(() => getTemplateConfig(name))
      .then(
        (loaded) => {
          if (this.doc !== doc) return;
          doc.load = "ready";
          doc.draft = doc.saved = loaded?.config ?? null;
          doc.revision = loaded?.revision ?? "";
          this.fence(doc, doc.revision);
          doc.save = loaded ? { kind: "saved", savedAt: Date.parse(loaded.modifiedAt) } : IDLE;
          this.emit();
        },
        () => {
          if (this.doc !== doc) return;
          doc.load = "error";
          this.emit();
        },
      );
    return doc;
  }

  private edited(doc: Doc) {
    doc.due = false;
    doc.loop.edit({ always: false });
    this.emit();
  }

  private held(doc: Doc): boolean {
    return doc.previewPending && doc.draft?.renderer.type === "marigold";
  }

  /** A switch flushes rather than drops: the edit was made, and the template
   * it was made to still exists. Not held by a preview: its editor is going. */
  private detach(doc: Doc) {
    doc.due = false;
    this.leave(doc);
  }

  /** The next read waits for `doc`'s writes. */
  private leave(doc: Doc) {
    this.leaving = Promise.all([this.leaving, doc.loop.flush()]);
  }

  /** Reads the draft now, not when the save was asked for, so it goes as the
   * one request the latest draft needs, and an edit undone sends nothing. */
  private async send(doc: Doc, always: boolean): Promise<Settled> {
    if (doc.load !== "ready" || doc.draft === null || (!always && !isDirty(doc))) return WRITTEN;
    const config = doc.draft;
    const edits = this.uncommitted(doc.maskEdits);
    doc.save = SAVING;
    this.emit();
    await this.adoptPreparedBaseline(doc);
    const result = await saveTemplateConfig(doc.name, config, edits, doc.revision);
    if (result.revision) doc.revision = result.revision;
    this.landed(doc, config, edits);
    return WRITTEN;
  }

  /** `config` and `edits` are on disk at `doc.revision`. */
  private landed(doc: Doc, config: TemplateConfigState, edits: MaskEdit[]) {
    const relabelling =
      edits.length === 0 && doc.saved !== null && onlyLabelsDiffer(doc.saved, config);
    for (const edit of edits) for (const op of edit.operations) this.committed.add(op);
    doc.saved = config;
    doc.maskEdits = this.uncommitted(doc.maskEdits);
    if (relabelling) doc.relabelled = [...doc.relabelled, doc.revision];
    else this.fence(doc, doc.revision);
    doc.save = { kind: "saved", savedAt: Date.now() };
    const current = this.doc === doc;
    // A save rebuilds CPU-side maps, so preparation is read again. A label
    // save rebuilds nothing.
    if (current && !relabelling) this.version += 1;
    this.emit();
    // Whether the template still needs calibration may have changed, and
    // the rail is what shows that. Only the open template is reselected: a
    // flushed one finishing late must not pull the rail back to it.
    this.connections.onCatalogChanged?.(current ? doc.name : undefined);
  }

  /** A completed preparation this session queued rewrites template.yaml's
   * revision without changing what this session saved. Adopt that revision
   * as the `If-Match` baseline -- but only while the disk still holds exactly
   * the saved document at exactly the prepared revision, so an external edit
   * made since is still refused as a conflict. */
  private async adoptPreparedBaseline(doc: Doc) {
    const preparation = this.preparation;
    const job = preparation?.latest_job;
    if (
      !job ||
      job.phase !== "completed" ||
      job.template !== doc.name ||
      !this.own.has(job.id) ||
      job.config_revision !== preparation?.config_revision ||
      doc.saved === null
    )
      return;
    if (doc.revision !== job.config_revision) {
      const disk = await getTemplateConfig(doc.name).catch(() => null);
      if (disk?.revision !== job.config_revision || !sameConfig(disk.config, doc.saved)) return;
      doc.revision = job.config_revision;
    }
    this.own.delete(job.id);
  }

  /** Moves what a preview names to `revision`, which holds the saved labels. */
  private fence(doc: Doc, revision: string) {
    doc.fence = revision;
    doc.fenceLabels = doc.saved?.labels ?? NO_LABELS;
    doc.relabelled = [];
  }

  private uncommitted(edits: MaskEdit[]): MaskEdit[] {
    const remaining = edits
      .map((edit) => ({
        ...edit,
        operations: edit.operations.filter((op) => !this.committed.has(op)),
      }))
      .filter((edit) => edit.operations.length > 0);
    return remaining.length ? remaining : NO_EDITS;
  }

  private emit() {
    this.view = this.render();
    for (const listener of this.listeners) listener();
  }

  private render(): View {
    const doc = this.doc;
    const ready = doc?.load === "ready";
    return {
      name: doc?.name ?? null,
      load: doc?.load ?? "none",
      config: ready ? doc.draft : null,
      saved: ready ? doc.saved : null,
      dirty: doc ? isDirty(doc) : false,
      save: doc ? shownSave(doc) : IDLE,
      maskEdits: doc?.maskEdits ?? NO_EDITS,
      calibrationRevision: doc?.fence ?? "",
      calibrationLabels: doc?.fenceLabels ?? NO_LABELS,
      relabelledRevisions: doc?.relabelled ?? [],
      previewPending: doc?.previewPending ?? false,
      preparationVersion: this.version,
      preparing: this.preparing,
      actionError: this.actionError,
    };
  }
}

/**
 * The calibrator's authoring session for the selected template: reading its
 * template.yaml, the draft against what was saved, autosave, the revision
 * every save names, mask strokes awaiting commit, and the preparation that
 * follows a save.
 *
 * Saves go through the {@link WriteLoop} the listing editor's use too: a
 * debounce from the last edit, one request in flight at a time, and pending
 * edits flushed -- not dropped -- on a template switch and on unmount. What
 * stays here is what differs: this PUTs a whole document over a revision, where
 * a listing merges patches and moves through create and rename, and a preview
 * can hold it.
 *
 * `onCatalogChanged` is told when a save or a queued preparation may have
 * changed the template list's facts, with the name to keep selected.
 */
export function useTemplateSession(
  name: string | null,
  options: { onCatalogChanged?: (select?: string) => void } = {},
): TemplateSession {
  const [session] = useState(() => new Session());
  const stored = useSyncExternalStore(session.subscribe, session.snapshot);
  // Until the effect below opens `name`, the store still holds the previous
  // template; it must not render under the new name.
  const view: View =
    stored.name === name
      ? stored
      : {
          ...stored,
          name,
          load: name === null ? "none" : "loading",
          config: null,
          saved: null,
          dirty: false,
          save: IDLE,
          maskEdits: NO_EDITS,
          calibrationRevision: "",
          calibrationLabels: NO_LABELS,
          relabelledRevisions: [],
          previewPending: false,
        };
  const {
    preparation,
    error: mapError,
    reload: reloadPreparation,
  } = usePreparation(name, view.preparationVersion, view.previewPending);
  const { onCatalogChanged } = options;

  useEffect(() => {
    session.connect({ reloadPreparation, onCatalogChanged });
  }, [session, reloadPreparation, onCatalogChanged]);
  useEffect(() => session.open(name), [session, name]);
  useEffect(() => session.observe(preparation), [session, preparation]);
  useEffect(() => () => session.close(), [session]);

  return {
    load: view.load,
    config: view.config,
    saved: view.saved,
    dirty: view.dirty,
    save: view.save,
    maskEdits: view.maskEdits,
    calibrationRevision: view.calibrationRevision,
    calibrationLabels: view.calibrationLabels,
    relabelledRevisions: view.relabelledRevisions,
    preparation,
    preparationError: view.actionError || mapError,
    preparing: view.preparing,
    update: session.update,
    setMaskEdits: session.setMaskEdits,
    setPreviewPending: session.setPreviewPending,
    flush: session.flush,
    approve: session.approve,
    reload: session.reload,
    prepare: session.prepare,
    cancelPreparation: session.cancelPreparation,
    reloadPreparation,
  };
}
