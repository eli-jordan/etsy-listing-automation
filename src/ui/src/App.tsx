import { usePreparationQueue } from "./hooks/usePreparationQueue";
import { RendererPanel } from "./components/RendererPanel";
import { preparationLabel } from "./components/preparationLabel";
import { InferenceSettings } from "./components/InferenceSettings";
import { MARIGOLD_DEFAULTS } from "./editors/marigoldDefaults";
import { MarigoldEditor } from "./editors/MarigoldEditor";
import { usePreparation } from "./hooks/usePreparation";
import { useTemplateReadiness } from "./hooks/useTemplateReadiness";
import {
  cancelPreparation,
  prepareTemplate,
  getPreparation,
  type MaskEdit,
} from "./api/preparation";
import type { Renderer } from "./types";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  acknowledgedTemplateRevision,
  getTemplateConfig,
  listTemplates,
  refreshPreparedRevision,
  saveTemplateConfig,
} from "./api/calibrator";
import { KindPicker } from "./components/KindPicker";
import { TemplateRail } from "./components/TemplateRail";
import { ColourMatrixEditor } from "./editors/ColourMatrixEditor";
import { MultipleEditor } from "./editors/MultipleEditor";
import { SingleEditor } from "./editors/SingleEditor";
import { AUTOSAVE_DEBOUNCE_MS } from "./hooks/useAutosave";
import { SavedAgo } from "./pages/editor/SavedAgo";
import type { TemplateConfigState, TemplateKind, TemplateSummary } from "./types";

/** A thin router: loads the selected template's config and picks an editor
 * by `kind` -- a template.yaml is exactly one of three shapes, never a mix.
 *
 * Wireframe 2a turns the page into a workbench: the rail on the left picks the
 * template (replacing the dropdown that used to sit in the header), and the
 * header becomes a breadcrumb saying what is open, whether it is finished, and
 * what it holds. */

const KIND_LABELS: Record<TemplateKind, string> = {
  "colour-matrix": "Colour Matrix",
  multiple: "Multiple",
  single: "Single",
};

export function App() {
  const preparationJobs = usePreparationQueue();
  const [maskDraft, setMaskDraft] = useState<{ name: string; edits: MaskEdit[] } | null>(null);
  const [preparationVersion, setPreparationVersion] = useState(0);
  const [calibrationFence, setCalibrationFence] = useState<{
    name: string;
    revision: string;
  } | null>(null);
  const ownPreparations = useRef(new Set<string>());
  const [preparing, setPreparing] = useState(false);
  const [preparationError, setPreparationError] = useState("");
  const rendererCache = useRef<Record<string, Partial<Record<Renderer["type"], Renderer>>>>({});
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [templateName, setTemplateName] = useState<string | null>(null);
  const {
    preparation,
    error: mapError,
    reload: reloadPreparation,
  } = usePreparation(templateName, preparationVersion);
  const maskEdits = useMemo(
    () => (maskDraft?.name === templateName ? maskDraft.edits : []),
    [maskDraft, templateName],
  );
  // Tagged with the name it was fetched for, so a template switch never
  // briefly renders the previous template's config under the new name while
  // the fetch for the new one is still in flight.
  const [configEntry, setConfigEntry] = useState<{
    name: string;
    config: TemplateConfigState;
  } | null>(null);
  // What is on disk. Reset goes back to this, and comparing against it is what
  // makes "are there unsaved edits?" answerable without a re-fetch.
  const [savedEntry, setSavedEntry] = useState<{
    name: string;
    config: TemplateConfigState;
  } | null>(null);
  const authoringState = useRef({ preparation, savedEntry });
  useEffect(() => {
    authoringState.current = { preparation, savedEntry };
  }, [preparation, savedEntry]);
  const [configLoad, setConfigLoad] = useState<{
    name: string;
    version: number;
    phase: "ready" | "error";
  } | null>(null);
  const [status, setStatus] = useState("");
  const [savedAt, setSavedAt] = useState<number | null>(null);
  // Which test artwork the previews render with. A way of looking at a
  // template rather than a property of one, so it lives here and never enters
  // template.yaml -- and it deliberately survives switching template, since
  // "show me all of these against my real artwork" is the point of changing it.
  const [design, setDesign] = useState("bundled-grid");
  // Bumped when a kind is assigned, to re-run the config fetch for a template
  // whose name has not changed but which now has a template.yaml.
  const [configVersion, setConfigVersion] = useState(0);

  // Refreshes overlap: assigning a kind fires one and saving fires another
  // moments later. They are separate requests, so the *older* can resolve
  // last -- putting the pre-assignment list back and reverting the template to
  // "no kind set" on screen while the file on disk says otherwise. The
  // sequence number makes a late response a no-op instead.
  const refreshSeq = useRef(0);
  const saveSeq = useRef(0);
  const currentTemplate = useRef<string | null>(templateName);

  useEffect(() => {
    currentTemplate.current = templateName;
  }, [templateName]);

  const refreshTemplates = useCallback((selectName?: string) => {
    const seq = ++refreshSeq.current;
    listTemplates()
      .then((loaded) => {
        if (seq !== refreshSeq.current) return;
        setTemplates(loaded);
        setTemplateName((current) => selectName ?? current ?? loaded[0]?.name ?? null);
      })
      .catch(() => {
        if (seq !== refreshSeq.current) return;
        setStatus("failed to load templates");
      });
  }, []);

  useEffect(() => {
    refreshTemplates();
  }, [refreshTemplates]);

  useEffect(() => {
    if (!templateName) return;
    // Same guard as the template list: assigning a kind bumps configVersion
    // while the previous fetch may still be in flight, and the stale answer
    // (no template.yaml) would put the kind picker back over a template that
    // now has one.
    let current = true;
    getTemplateConfig(templateName)
      .then((loaded) => {
        if (!current) return;
        setConfigLoad({ name: templateName, version: configVersion, phase: "ready" });
        const entry = loaded ? { name: templateName, config: loaded.config } : null;
        setConfigEntry(entry);
        setSavedEntry(entry);
        setCalibrationFence(
          loaded
            ? {
                name: templateName,
                revision: acknowledgedTemplateRevision(templateName),
              }
            : null,
        );
        setSavedAt(loaded ? Date.parse(loaded.modifiedAt) : null);
        setStatus(loaded ? "Saved" : "");
      })
      .catch(() => {
        if (current) {
          setConfigLoad({ name: templateName, version: configVersion, phase: "error" });
          setStatus("failed to load template config");
        }
      });
    return () => {
      current = false;
    };
  }, [templateName, configVersion]);

  useEffect(() => {
    const completed = preparation?.latest_job;
    if (
      completed?.phase !== "completed" ||
      !ownPreparations.current.has(completed.id) ||
      completed.config_revision !== preparation?.config_revision
    )
      return;
    setCalibrationFence((current) =>
      current?.name === completed.template && current.revision === completed.config_revision
        ? current
        : { name: completed.template, revision: completed.config_revision },
    );
  }, [preparation]);

  const mapState = preparation?.maps.state;
  const preparationPhase = preparation?.active_job?.phase;
  useEffect(() => {
    if (mapState) refreshTemplates();
  }, [mapState, preparationPhase, refreshTemplates]);
  const config = configEntry?.name === templateName ? configEntry.config : null;
  const saved = savedEntry?.name === templateName ? savedEntry.config : null;

  const dirty = useMemo(
    () =>
      config !== null &&
      saved !== null &&
      (JSON.stringify(config) !== JSON.stringify(saved) || maskEdits.length > 0),
    [config, saved, maskEdits],
  );

  const setConfig = useCallback(
    (next: TemplateConfigState) => {
      if (!templateName) return;
      setConfigEntry({ name: templateName, config: next });
    },
    [templateName],
  );

  const saveConfig = useCallback(
    (name: string, next: TemplateConfigState, edits: MaskEdit[] = []) => {
      const seq = ++saveSeq.current;
      setStatus("Saving…");
      const current = authoringState.current;
      const completed = current.preparation?.latest_job;
      const sync =
        completed?.phase === "completed" &&
        completed.template === name &&
        ownPreparations.current.has(completed.id) &&
        completed.config_revision === current.preparation?.config_revision &&
        current.savedEntry?.name === name
          ? refreshPreparedRevision(
              name,
              current.savedEntry.config,
              completed.config_revision,
            ).then((accepted) => {
              if (accepted) ownPreparations.current.delete(completed.id);
            })
          : Promise.resolve();
      return sync
        .then(() => saveTemplateConfig(name, next, edits))
        .then(() => {
          setMaskDraft((current) => {
            if (current?.name !== name) return current;
            const remaining = current.edits
              .map((edit) => {
                const committed =
                  edits.find((e) => e.placement_id === edit.placement_id)?.operations ?? [];
                return {
                  ...edit,
                  operations: edit.operations.filter((op) => !committed.includes(op)),
                };
              })
              .filter((edit) => edit.operations.length > 0);
            return remaining.length ? { name, edits: remaining } : null;
          });
          if (seq !== saveSeq.current || name !== currentTemplate.current) return;
          setSavedEntry({ name, config: next });
          setCalibrationFence({ name, revision: acknowledgedTemplateRevision(name) });

          setPreparationVersion((v) => v + 1);
          setSavedAt(Date.now());
          setStatus("Saved");
          // The save may have changed whether this template still counts as
          // needing calibration, and the rail is what shows that.
          refreshTemplates(name);
        })
        .catch((e: unknown) => {
          if (seq === saveSeq.current && name === currentTemplate.current)
            setStatus(e instanceof Error ? e.message : "Save failed");
          throw e;
        });
    },
    [refreshTemplates],
  );

  // Match the listing editor: wait until a run of edits settles, then write
  // it as one request. Changing template or resetting clears the pending
  // timer through the effect cleanup.
  useEffect(() => {
    if (!templateName || !config || !dirty) return;
    const timer = setTimeout(
      () => void saveConfig(templateName, config, maskEdits).catch(() => {}),
      AUTOSAVE_DEBOUNCE_MS,
    );
    return () => clearTimeout(timer);
  }, [config, dirty, saveConfig, templateName, maskEdits]);

  const handleApprove = useCallback(() => {
    if (!templateName || !config) return;
    void saveConfig(templateName, config, maskEdits).catch(() => {});
  }, [templateName, config, saveConfig, maskEdits]);

  const handleReset = useCallback(() => {
    if (!templateName || !saved) return;
    setConfigEntry({ name: templateName, config: saved });
    setMaskDraft(null);
    setStatus("reset");
  }, [templateName, saved]);

  const selectTemplate = useCallback((name: string) => {
    setStatus("");
    setSavedAt(null);
    setTemplateName(name);
  }, []);

  const startPreparation = useCallback(
    async (
      action: "prepare" | "prepare_again" | "retry" = "prepare",
      resetMasksForPhoto = false,
    ) => {
      if (!templateName || !config || preparing) return;
      setPreparing(true);
      setPreparationError("");
      try {
        const staleIds = new Set(
          preparation?.placements
            .filter((p) => !p.mask_available && p.mask_reason?.toLowerCase().includes("photo"))
            .map((p) => p.placement_id),
        );
        const validEdits = resetMasksForPhoto
          ? maskEdits.filter((edit) => !staleIds.has(edit.placement_id ?? null))
          : maskEdits;
        if (resetMasksForPhoto)
          setMaskDraft(validEdits.length ? { name: templateName, edits: validEdits } : null);
        if (dirty) await saveConfig(templateName, config, validEdits);
        const current = await getPreparation(templateName);
        const submitted = await prepareTemplate({
          template: templateName,
          config_revision: current.config_revision,
          request_id: crypto.randomUUID(),
          action,
          reset_masks_for_photo: resetMasksForPhoto,
          ...(action === "retry" && current.latest_job
            ? { previous_job: current.latest_job.id }
            : {}),
        });
        ownPreparations.current.add(submitted.id);
        reloadPreparation();
        refreshTemplates();
      } catch (e) {
        setPreparationError(e instanceof Error ? e.message : "Preparation could not start");
      } finally {
        setPreparing(false);
      }
    },
    [
      templateName,
      config,
      preparing,
      dirty,
      saveConfig,
      maskEdits,
      preparation,
      reloadPreparation,
      refreshTemplates,
    ],
  );
  const stopPreparation = async () => {
    if (!preparation?.active_job) return;
    setPreparing(true);
    try {
      await cancelPreparation(preparation.active_job.id);
      reloadPreparation();
    } catch (e) {
      setPreparationError(e instanceof Error ? e.message : "Cancellation failed");
    } finally {
      setPreparing(false);
    }
  };
  const switchRenderer = (type: Renderer["type"]) => {
    if (!config || !templateName || type === config.renderer.type) return;
    const cache = rendererCache.current[templateName] ?? {};
    cache[config.renderer.type] = config.renderer;
    rendererCache.current[templateName] = cache;
    const stored = preparation?.renderer_settings[type];
    const renderer =
      cache[type] ??
      (stored
        ? ({ type, config: stored } as Renderer)
        : type === "marigold"
          ? MARIGOLD_DEFAULTS
          : {
              type: "photo-warp",
              config: {
                displace: { enabled: false, strength: 0 },
                shade: { enabled: true, opacity: 0.6, blend: "soft-light" },
              },
            });
    setConfig({ ...config, renderer });
  };
  const queueKey = preparationJobs
    .filter((job) => job.template === templateName)
    .map((job) => job.id + job.phase)
    .join(",");
  const previousQueueKey = useRef(queueKey);
  useEffect(() => {
    if (previousQueueKey.current !== queueKey) reloadPreparation();
    previousQueueKey.current = queueKey;
  }, [queueKey, reloadPreparation]);
  const railFacts = useTemplateReadiness(templates, templateName, preparationJobs);
  const railTemplates = useMemo(
    () =>
      templates.map((template) =>
        preparation?.template === template.name
          ? { ...template, maps: preparation.maps }
          : { ...template, maps: railFacts[template.name] ?? template.maps ?? null },
      ),
    [templates, preparation, railFacts],
  );
  const selected = templates.find((t) => t.name === templateName);
  const rendererControls =
    config && templateName ? (
      <RendererPanel
        renderer={config.renderer}
        reference={
          preparation
            ? "Main image: " +
              preparation.main_photo.split(/[\\/]/).at(-1) +
              (config.kind === "colour-matrix"
                ? " · shared across " + selected?.colours.length + " colours"
                : config.kind === "multiple"
                  ? " · all placements"
                  : "")
            : ""
        }
        onRendererChange={switchRenderer}
        preparation={preparation}
        onPrepare={(action, recovery) => void startPreparation(action, recovery)}
        onCancel={() => void stopPreparation()}
        pending={preparing}
        error={preparationError || mapError}
        settings={(runtime) =>
          config.renderer.type === "marigold" ? (
            <InferenceSettings
              templateName={templateName}
              value={config.renderer.config.inference}
              capabilityKnown={Boolean(runtime)}
              {...(runtime
                ? {
                    limits: {
                      num_inference_steps: runtime.max_num_inference_steps,
                      ensemble_size: runtime.max_ensemble_size,
                    },
                  }
                : {})}
              onSave={(inference) => {
                if (config.renderer.type === "marigold")
                  setConfig({
                    ...config,
                    renderer: {
                      ...config.renderer,
                      config: { ...config.renderer.config, inference },
                    },
                  });
              }}
            />
          ) : null
        }
      />
    ) : null;

  // Every colour already in use anywhere in the workspace, for the box
  // colour field's suggestions. Suggestions rather than a closed list: a
  // chart's colours are whatever the listing sells, and nothing here knows
  // that -- wiring in the Printify catalog would be a much larger dependency.
  const knownColours = useMemo(
    () => [...new Set(templates.flatMap((t) => t.colours))].filter(Boolean).sort(),
    [templates],
  );
  const kindLabel = selected?.kind ? KIND_LABELS[selected.kind] : null;

  // The photo's true pixel size, which is the coordinate space every bounding
  // box in template.yaml is written in. It has to come from the API: the
  // editors' canvas renders a downscale now, so measuring the image on screen
  // would put the boxes in the preview's space and save them several times too
  // small. `null` for a directory with no readable photo -- there is nothing
  // to calibrate against, and the editors say so rather than guessing.
  const space: [number, number] | null =
    selected?.width && selected.height ? [selected.width, selected.height] : null;

  return (
    <div className={config?.renderer.type === "marigold" ? "app mg-frame mg-app" : "app mg-frame"}>
      <header className="app__header">
        <h1 className="app__title">Mockup Templates</h1>
        {selected && (
          <>
            <span className="app__crumb-sep">/</span>
            <span className="app__crumb">{selected.name}</span>
            {config && config.renderer.type !== "marigold" && (
              <span
                className={selected.status === "calibrated" ? "tag tag-accent-2" : "tag tag-accent"}
              >
                {selected.status === "calibrated" ? "calibrated" : "needs calibration"}
              </span>
            )}
            {config?.renderer.type === "marigold" && (
              <span
                className={
                  "tag mg-status" +
                  (preparation?.maps.can_render
                    ? " mg-status--ready"
                    : preparation?.latest_job?.phase === "failed"
                      ? " mg-status--failed"
                      : "")
                }
              >
                {preparationLabel(preparation)}
              </span>
            )}
            <span className="app__meta">
              {config?.kind === "multiple"
                ? "Multiple · " + config.placements.length + " placements"
                : selected.status === "calibrated"
                  ? `${kindLabel ?? "Unknown"} · ${selected.colours.length} colour${
                      selected.colours.length === 1 ? "" : "s"
                    }`
                  : (selected.status_reason ?? "not calibrated")}
            </span>
          </>
        )}

        <div className="app__actions">
          <p className="app__status" role="status">
            {status === "Saved" && savedAt !== null ? (
              <span className="page-head__saved">
                <span className="page-head__dot" aria-hidden="true" />
                <SavedAgo savedAt={savedAt} />
              </span>
            ) : (
              status
            )}
          </p>
          {status.includes("changed elsewhere") && (
            <button
              onClick={() => {
                setMaskDraft(null);
                setConfigVersion((v) => v + 1);
                setStatus("");
              }}
            >
              Reload template
            </button>
          )}
          <button className="btn btn-secondary" onClick={handleReset} disabled={!dirty}>
            Reset
          </button>
        </div>
      </header>

      <div className="app__workbench">
        <TemplateRail
          templates={railTemplates}
          selectedPreparationStatus={
            config?.renderer.type === "marigold" ? preparationLabel(preparation) : null
          }
          selected={templateName}
          onSelect={selectTemplate}
          jobs={preparationJobs}
        />

        <div className="app__workspace">
          {/* 2a: an uncalibrated template replaces the workspace with a single
              choice, so nothing else can be touched yet. Kind decides the
              whole shape of template.yaml (ADR-0014) -- every other control is
              meaningless or wrong until it is answered. */}
          {templateName &&
          (configLoad?.name !== templateName ||
            configLoad.version !== configVersion ||
            configLoad.phase !== "ready") ? (
            <p role={configLoad?.phase === "error" ? "alert" : "status"}>
              {configLoad?.phase === "error"
                ? "Could not load template configuration. Reload to try again."
                : "Loading template..."}
            </p>
          ) : templateName && !config ? (
            <KindPicker
              key={templateName}
              templateName={templateName}
              onAssigned={() => {
                setConfigVersion((v) => v + 1);
                refreshTemplates(templateName);
              }}
            />
          ) : (
            <>
              {templateName && config?.renderer.type === "marigold" && (
                <MarigoldEditor
                  key={templateName}
                  templateName={templateName}
                  config={{ ...config, renderer: config.renderer }}
                  space={space}
                  colours={selected?.colours ?? []}
                  knownColours={knownColours}
                  design={design}
                  onDesignChange={setDesign}
                  onChange={setConfig}
                  preparation={preparation}
                  rendererControls={rendererControls}
                  calibrationRevision={
                    calibrationFence?.name === templateName ? calibrationFence.revision : ""
                  }
                  maskEdits={maskEdits}
                  onMaskEdits={(edits) => setMaskDraft({ name: templateName, edits })}
                  savedConfig={saved}
                  onPrepare={() =>
                    void startPreparation(
                      preparation?.maps.reason === "photo_changed" ? "prepare_again" : "prepare",
                      preparation?.maps.reason === "photo_changed",
                    )
                  }
                />
              )}
              {templateName &&
                config?.renderer.type === "photo-warp" &&
                config?.kind === "colour-matrix" && (
                  <ColourMatrixEditor
                    key={templateName}
                    rendererControls={rendererControls}
                    templateName={templateName}
                    config={config}
                    space={space}
                    colours={selected?.colours ?? []}
                    onChange={setConfig}
                    design={design}
                    onDesignChange={setDesign}
                    onApprove={handleApprove}
                  />
                )}
              {templateName &&
                config?.renderer.type === "photo-warp" &&
                config?.kind === "multiple" && (
                  <MultipleEditor
                    key={templateName}
                    rendererControls={rendererControls}
                    templateName={templateName}
                    config={config}
                    space={space}
                    onChange={setConfig}
                    design={design}
                    onDesignChange={setDesign}
                    knownColours={knownColours}
                  />
                )}
              {templateName &&
                config?.renderer.type === "photo-warp" &&
                config?.kind === "single" && (
                  <SingleEditor
                    key={templateName}
                    rendererControls={rendererControls}
                    templateName={templateName}
                    config={config}
                    space={space}
                    onChange={setConfig}
                    design={design}
                    onDesignChange={setDesign}
                  />
                )}
              {/* Templates are folders in the workspace, not something this
                  page creates: the calibrator calibrates. */}
              {!templateName && (
                <p>No templates yet -- add a folder of photos under mockup-templates/.</p>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
