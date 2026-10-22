import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { listTemplates } from "./api/calibrator";
import { InferenceSettings } from "./components/InferenceSettings";
import { KindPicker } from "./components/KindPicker";
import { preparationLabel, marigoldMapsReady } from "./components/preparationLabel";
import { RendererPanel } from "./components/RendererPanel";
import { TemplateRail } from "./components/TemplateRail";
import { ColourMatrixEditor } from "./editors/ColourMatrixEditor";
import { MARIGOLD_DEFAULTS } from "./editors/marigoldDefaults";
import { MarigoldEditor } from "./editors/MarigoldEditor";
import { MultipleEditor } from "./editors/MultipleEditor";
import { SingleEditor } from "./editors/SingleEditor";
import { usePreparationQueue } from "./hooks/usePreparationQueue";
import { useTemplateReadiness } from "./hooks/useTemplateReadiness";
import { useTemplateSession } from "./hooks/useTemplateSession";
import { SavedAgo } from "./pages/editor/SavedAgo";
import type { Renderer, TemplateKind, TemplateSummary } from "./types";

/** A thin router: picks the template, hands it to an authoring session
 * (`useTemplateSession`, which reads, saves and prepares it) and picks an
 * editor by `kind` -- a template.yaml is exactly one of three shapes, never a
 * mix.
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
  const rendererCache = useRef<Record<string, Partial<Record<Renderer["type"], Renderer>>>>({});
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [catalogState, setCatalogState] = useState<"loading" | "ready" | "error">("loading");
  const [templateName, setTemplateName] = useState<string | null>(null);
  // Which test artwork the previews render with. A way of looking at a
  // template rather than a property of one, so it lives here and never enters
  // template.yaml -- and it deliberately survives switching template, since
  // "show me all of these against my real artwork" is the point of changing it.
  const [design, setDesign] = useState("bundled-grid");

  // Refreshes overlap: assigning a kind fires one and saving fires another
  // moments later. They are separate requests, so the *older* can resolve
  // last -- putting the pre-assignment list back and reverting the template to
  // "no kind set" on screen while the file on disk says otherwise. The
  // sequence number makes a late response a no-op instead.
  const refreshSeq = useRef(0);
  const currentTemplate = useRef<string | null>(templateName);

  useEffect(() => {
    currentTemplate.current = templateName;
  }, [templateName]);

  const refreshTemplates = useCallback((selectName?: string) => {
    const seq = ++refreshSeq.current;
    const selectionAtRequest = currentTemplate.current;
    listTemplates()
      .then((loaded) => {
        if (seq !== refreshSeq.current) return;
        setCatalogState("ready");
        setTemplates(loaded);
        // A save may finish its catalog refresh after the user has moved on.
        setTemplateName(
          (current) =>
            (current === selectionAtRequest ? selectName : undefined) ??
            current ??
            loaded[0]?.name ??
            null,
        );
      })
      .catch(() => {
        if (seq !== refreshSeq.current) return;
        setCatalogState("error");
      });
  }, []);

  useEffect(() => {
    refreshTemplates();
  }, [refreshTemplates]);

  const session = useTemplateSession(templateName, { onCatalogChanged: refreshTemplates });
  const { config, preparation, preparing, save, update: setConfig, reloadPreparation } = session;

  const mapState = preparation?.maps.state;
  useEffect(() => {
    if (mapState) refreshTemplates();
  }, [mapState, refreshTemplates]);

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
        onRendererChange={switchRenderer}
        preparation={preparation}
        onPrepare={(action, recovery) => void session.prepare(action, recovery)}
        onCancel={() => void session.cancelPreparation()}
        pending={preparing}
        error={session.preparationError}
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
                  (!preparing && marigoldMapsReady(preparation?.maps)
                    ? " mg-status--ready"
                    : preparation?.latest_job?.phase === "failed"
                      ? " mg-status--failed"
                      : "")
                }
              >
                {preparing ? "Preparing" : preparationLabel(preparation)}
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
            {save.kind === "saved" ? (
              <span className="page-head__saved">
                <span className="page-head__dot" aria-hidden="true" />
                <SavedAgo savedAt={save.savedAt} />
              </span>
            ) : save.kind === "saving" ? (
              "Saving…"
            ) : save.kind === "failed" || save.kind === "conflict" ? (
              save.message
            ) : session.load === "error" ? (
              "failed to load template config"
            ) : catalogState === "error" ? (
              "failed to load templates"
            ) : (
              ""
            )}
          </p>
          {save.kind === "conflict" && <button onClick={session.reload}>Reload template</button>}
        </div>
      </header>

      <div className="app__workbench">
        <TemplateRail
          templates={railTemplates}
          selectedPreparationStatus={
            config?.renderer.type === "marigold"
              ? preparing
                ? "Preparing"
                : preparationLabel(preparation)
              : null
          }
          selected={templateName}
          onSelect={setTemplateName}
          jobs={preparationJobs}
        />

        <div className="app__workspace">
          {/* 2a: an uncalibrated template replaces the workspace with a single
              choice, so nothing else can be touched yet. Kind decides the
              whole shape of template.yaml (ADR-0014) -- every other control is
              meaningless or wrong until it is answered. */}
          {templateName && session.load !== "ready" ? (
            <p role={session.load === "error" ? "alert" : "status"}>
              {session.load === "error"
                ? "Could not load template configuration. Reload to try again."
                : "Loading template..."}
            </p>
          ) : templateName && !config ? (
            <KindPicker
              key={templateName}
              templateName={templateName}
              onAssigned={() => {
                session.reload();
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
                  calibrationRevision={session.calibrationRevision}
                  maskEdits={session.maskEdits}
                  onMaskEdits={session.setMaskEdits}
                  onPreviewPending={session.setPreviewPending}
                  savedConfig={session.saved}
                  onPrepare={() =>
                    void session.prepare(
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
                    onApprove={() => void session.approve()}
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
              {!templateName &&
                (catalogState === "loading" ? (
                  <p role="status">Loading templates...</p>
                ) : catalogState === "error" ? (
                  <p role="alert">Could not load templates. Reload to try again.</p>
                ) : (
                  <p>No templates yet -- add a folder of photos under mockup-templates/.</p>
                ))}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
