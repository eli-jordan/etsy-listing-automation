import { useEffect, useState, useSyncExternalStore } from "react";
import {
  CalibratorApiError,
  getTemplateConfig,
  saveTemplateConfig,
  TemplateConflictError,
} from "../api/calibrator";
import {
  cancelPreparation,
  getPreparation,
  prepareTemplate,
  type MaskEdit,
  type MaskOperation,
  type Preparation,
  type PreparationJob,
} from "../api/preparation";
import type { TemplateConfigState } from "../types";
import { WriteLoop, WRITTEN, type Settled } from "./writeLoop";
import { usePreparation } from "./usePreparation";

export type TemplateSaveState =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved"; savedAt: number }
  | { kind: "failed"; message: string }
  | { kind: "conflict"; message: string };

export type TemplateLoad = "none" | "loading" | "ready" | "error";

export type PreparationAction = "prepare" | "prepare_again" | "retry";

export interface TemplateSession {
  load: TemplateLoad;
  loadError: string | null;
  /** The draft: the document as last read or saved, plus every edit since. */
  config: TemplateConfigState | null;
  saved: TemplateConfigState | null;
  dirty: boolean;
  save: TemplateSaveState;
  maskEdits: MaskEdit[];
  calibrationRevision: string;
  calibrationLabels: string[];
  relabelledRevisions: string[];
  preparation: Preparation | null;
  preparationError: string;
  preparing: boolean;
  update: (config: TemplateConfigState) => void;
  setMaskEdits: (edits: MaskEdit[]) => void;
  setPreviewPending: (pending: boolean) => void;
  flush: () => Promise<Settled>;
  approve: () => Promise<Settled>;
  reload: () => void;
  prepare: (action?: PreparationAction, resetMasksForPhoto?: boolean) => Promise<void>;
  cancelPreparation: () => Promise<void>;
  reloadPreparation: () => void;
}

function withSortedKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(withSortedKeys);
  if (value !== null && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, withSortedKeys(item)]),
    );
  return value;
}

function sameConfig(left: TemplateConfigState, right: TemplateConfigState): boolean {
  return JSON.stringify(withSortedKeys(left)) === JSON.stringify(withSortedKeys(right));
}

function sameLabels(left: TemplateConfigState, right: TemplateConfigState): boolean {
  return JSON.stringify(left.labels) === JSON.stringify(right.labels);
}

function onlyLabelsDiffer(before: TemplateConfigState, after: TemplateConfigState): boolean {
  return !sameLabels(before, after) && sameConfig({ ...before, labels: after.labels }, after);
}

interface Opening {
  name: string;
  load: "loading" | "ready" | "error";
  loadError: string | null;
  draft: TemplateConfigState | null;
  saved: TemplateConfigState | null;
  ifMatchRevision: string;
  previewRevision: string;
  previewLabels: string[];
  relabelled: string[];
  maskEdits: MaskEdit[];
  save: TemplateSaveState;
  previewPending: boolean;
  loop: WriteLoop<SaveWanted>;
  dueWhileHeld: boolean;
}

interface SaveWanted {
  always: boolean;
}

interface View {
  name: string | null;
  load: TemplateLoad;
  loadError: string | null;
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
  onCatalogChanged: (() => void) | undefined;
}

const IDLE: TemplateSaveState = { kind: "idle" };
const SAVING: TemplateSaveState = { kind: "saving" };
const NO_EDITS: MaskEdit[] = [];
const NO_LABELS: string[] = [];

function saveFailure(e: unknown): Extract<TemplateSaveState, { message: string }> {
  if (e instanceof TemplateConflictError) return { kind: "conflict", message: e.message };
  return { kind: "failed", message: e instanceof Error ? e.message : "Save failed" };
}

function isDirty(doc: Opening): boolean {
  return (
    doc.draft !== null &&
    doc.saved !== null &&
    (!sameConfig(doc.draft, doc.saved) || doc.maskEdits.length > 0)
  );
}

function shownSave(doc: Opening): TemplateSaveState {
  const waiting = doc.loop.armed || doc.dueWhileHeld;
  const labelled = doc.draft !== null && doc.saved !== null && !sameLabels(doc.draft, doc.saved);
  const settled = doc.save.kind === "idle" || doc.save.kind === "saved";
  return waiting && labelled && settled ? SAVING : doc.save;
}

/** Outside React, so the save loop reads current state, not a render's closure. */
class Session {
  private doc: Opening | null = null;
  private listeners = new Set<() => void>();
  private leaving: Promise<unknown> = Promise.resolve();
  /** Operations are objects shared by successive draft snapshots, so an
   * editor handing back a list built before a save landed would otherwise
   * send its strokes twice. */
  private committed = new WeakSet<MaskOperation>();
  private ownJobs = new Set<string>();
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

  close() {
    if (this.doc) this.detach(this.doc);
  }

  observe(preparation: Preparation | null) {
    this.preparation = preparation;
    const doc = this.doc;
    const job = doc && this.ownCompletedJob(doc);
    if (doc && job && doc.previewRevision !== job.config_revision) {
      this.movePreviewRevision(doc, job.config_revision);
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
    if (doc.dueWhileHeld && !this.held(doc)) {
      doc.dueWhileHeld = false;
      void doc.loop.flush();
    }
    this.emit();
  };

  flush = (): Promise<Settled> => {
    const doc = this.doc;
    if (!doc) return Promise.resolve(WRITTEN);
    doc.dueWhileHeld = false;
    return doc.loop.flush();
  };

  approve = (): Promise<Settled> => {
    const doc = this.doc;
    if (!doc) return Promise.resolve(WRITTEN);
    doc.dueWhileHeld = false;
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
      this.ownJobs.add(submitted.id);
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

  private read(name: string): Opening {
    const doc: Opening = {
      name,
      load: "loading",
      loadError: null,
      draft: null,
      saved: null,
      ifMatchRevision: "",
      previewRevision: "",
      previewLabels: NO_LABELS,
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
          if (this.held(doc)) doc.dueWhileHeld = true;
          else void doc.loop.flush();
        },
      }),
      dueWhileHeld: false,
    };
    void this.leaving
      .then(() => getTemplateConfig(name))
      .then(
        (loaded) => {
          if (this.doc !== doc) return;
          doc.load = "ready";
          doc.draft = doc.saved = loaded?.config ?? null;
          doc.ifMatchRevision = loaded?.revision ?? "";
          this.movePreviewRevision(doc, doc.ifMatchRevision);
          doc.save = loaded ? { kind: "saved", savedAt: Date.parse(loaded.modifiedAt) } : IDLE;
          this.emit();
        },
        (e: unknown) => {
          if (this.doc !== doc) return;
          doc.load = "error";
          doc.loadError = e instanceof CalibratorApiError ? e.message : null;
          this.emit();
        },
      );
    return doc;
  }

  private edited(doc: Opening) {
    doc.dueWhileHeld = false;
    doc.loop.edit({ always: false });
    this.emit();
  }

  private held(doc: Opening): boolean {
    return doc.previewPending && doc.draft?.renderer.type === "marigold";
  }

  private detach(doc: Opening) {
    doc.dueWhileHeld = false;
    this.leave(doc);
  }

  private leave(doc: Opening) {
    this.leaving = Promise.all([this.leaving, doc.loop.flush()]);
  }

  private async send(doc: Opening, always: boolean): Promise<Settled> {
    if (doc.load !== "ready" || doc.draft === null || (!always && !isDirty(doc))) return WRITTEN;
    const config = doc.draft;
    const edits = this.uncommitted(doc.maskEdits);
    doc.save = SAVING;
    this.emit();
    await this.adoptPreparedBaseline(doc);
    const result = await saveTemplateConfig(doc.name, config, edits, doc.ifMatchRevision);
    if (result.revision) doc.ifMatchRevision = result.revision;
    this.landed(doc, config, edits);
    return WRITTEN;
  }

  private landed(doc: Opening, config: TemplateConfigState, edits: MaskEdit[]) {
    const relabelling =
      edits.length === 0 && doc.saved !== null && onlyLabelsDiffer(doc.saved, config);
    for (const edit of edits) for (const op of edit.operations) this.committed.add(op);
    doc.saved = config;
    doc.maskEdits = this.uncommitted(doc.maskEdits);
    if (relabelling) doc.relabelled = [...doc.relabelled, doc.ifMatchRevision];
    else this.movePreviewRevision(doc, doc.ifMatchRevision);
    doc.save = { kind: "saved", savedAt: Date.now() };
    const current = this.doc === doc;
    if (current && !relabelling) this.version += 1;
    this.emit();
    this.connections.onCatalogChanged?.();
  }

  private ownCompletedJob(doc: Opening): PreparationJob | null {
    const preparation = this.preparation;
    const job = preparation?.latest_job;
    if (
      job?.phase !== "completed" ||
      job.template !== doc.name ||
      !this.ownJobs.has(job.id) ||
      job.config_revision !== preparation?.config_revision
    )
      return null;
    return job;
  }

  private async adoptPreparedBaseline(doc: Opening) {
    const job = this.ownCompletedJob(doc);
    if (!job || doc.saved === null) return;
    if (doc.ifMatchRevision !== job.config_revision) {
      const disk = await getTemplateConfig(doc.name).catch(() => null);
      if (disk?.revision !== job.config_revision || !sameConfig(disk.config, doc.saved)) return;
      doc.ifMatchRevision = job.config_revision;
    }
    this.ownJobs.delete(job.id);
  }

  private movePreviewRevision(doc: Opening, revision: string) {
    doc.previewRevision = revision;
    doc.previewLabels = doc.saved?.labels ?? NO_LABELS;
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
      loadError: doc?.loadError ?? null,
      config: ready ? doc.draft : null,
      saved: ready ? doc.saved : null,
      dirty: doc ? isDirty(doc) : false,
      save: doc ? shownSave(doc) : IDLE,
      maskEdits: doc?.maskEdits ?? NO_EDITS,
      calibrationRevision: doc?.previewRevision ?? "",
      calibrationLabels: doc?.previewLabels ?? NO_LABELS,
      relabelledRevisions: doc?.relabelled ?? [],
      previewPending: doc?.previewPending ?? false,
      preparationVersion: this.version,
      preparing: this.preparing,
      actionError: this.actionError,
    };
  }
}

export function useTemplateSession(
  name: string | null,
  options: { onCatalogChanged?: () => void } = {},
): TemplateSession {
  const [session] = useState(() => new Session());
  const stored = useSyncExternalStore(session.subscribe, session.snapshot);
  // The store lags `name` until the effect below opens it.
  const view: View =
    stored.name === name
      ? stored
      : {
          ...stored,
          name,
          load: name === null ? "none" : "loading",
          loadError: null,
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
    loadError: view.loadError,
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
