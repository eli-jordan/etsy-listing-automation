import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { listTemplates } from "./api/calibrator";
import type { Preparation, Runtime } from "./api/preparation";
import { InferenceSettings } from "./components/InferenceSettings";
import { KindPicker } from "./components/KindPicker";
import { PositionedListingsNote } from "./components/PositionedListingsNote";
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
import {
  useTemplateSession,
  type TemplateLoad,
  type TemplateSaveState,
  type TemplateSession,
} from "./hooks/useTemplateSession";
import { SavedAgo } from "./pages/editor/SavedAgo";
import type { Renderer, TemplateConfigState, TemplateKind, TemplateSummary } from "./types";

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

type CatalogState = "loading" | "ready" | "error";

/** What switching to a renderer this template has no draft for starts from:
 * the settings its preparation stored, else the renderer's defaults. */
function fallbackRenderer(
  type: Renderer["type"],
  stored: Preparation["renderer_settings"][Renderer["type"]] | undefined,
): Renderer {
  if (stored) return { type, config: stored } as Renderer;
  if (type === "marigold") return MARIGOLD_DEFAULTS;
  return {
    type: "photo-warp",
    config: {
      displace: { enabled: false, strength: 0 },
      shade: { enabled: true, opacity: 0.6, blend: "soft-light" },
    },
  };
}

/** The inference limits the runtime reports, or none while it is unknown --
 * the settings form then keeps its own defaults. */
function runtimeLimits(runtime: Runtime | null) {
  if (!runtime) return {};
  return {
    limits: {
      num_inference_steps: runtime.max_num_inference_steps,
      ensemble_size: runtime.max_ensemble_size,
    },
  };
}

function marigoldStatusClass(preparing: boolean, preparation: Preparation | null): string {
  if (!preparing && marigoldMapsReady(preparation?.maps)) return " mg-status--ready";
  return preparation?.latest_job?.phase === "failed" ? " mg-status--failed" : "";
}

/** The breadcrumb's summary of what the open template holds. */
function templateMeta(selected: TemplateSummary, config: TemplateConfigState | null): string {
  if (config?.kind === "multiple") return "Multiple · " + config.placements.length + " placements";
  if (selected.status !== "calibrated") return selected.status_reason ?? "not calibrated";
  const kindLabel = selected.kind ? KIND_LABELS[selected.kind] : null;
  const colours = selected.colours.length;
  return `${kindLabel ?? "Unknown"} · ${colours} colour${colours === 1 ? "" : "s"}`;
}

function TemplateCrumb({
  selected,
  config,
  preparationStatus,
  statusClass,
}: {
  selected: TemplateSummary;
  config: TemplateConfigState | null;
  preparationStatus: string;
  statusClass: string;
}) {
  return (
    <>
      <span className="app__crumb-sep">/</span>
      <span className="app__crumb">{selected.name}</span>
      {config && config.renderer.type !== "marigold" && (
        <span className={selected.status === "calibrated" ? "tag tag-accent-2" : "tag tag-accent"}>
          {selected.status === "calibrated" ? "calibrated" : "needs calibration"}
        </span>
      )}
      {config?.renderer.type === "marigold" && (
        <span className={"tag mg-status" + statusClass}>{preparationStatus}</span>
      )}
      <span className="app__meta">{templateMeta(selected, config)}</span>
    </>
  );
}

function SaveStatus({
  save,
  load,
  catalogState,
}: {
  save: TemplateSaveState;
  load: TemplateLoad;
  catalogState: CatalogState;
}): ReactNode {
  if (save.kind === "saved") {
    return (
      <span className="page-head__saved">
        <span className="page-head__dot" aria-hidden="true" />
        <SavedAgo savedAt={save.savedAt} />
      </span>
    );
  }
  if (save.kind === "saving") return "Saving…";
  if (save.kind === "failed" || save.kind === "conflict") return save.message;
  if (load === "error") return "failed to load template config";
  return catalogState === "error" ? "failed to load templates" : "";
}

/** The workspace with no template open. Templates are folders in the
 * workspace, not something this page creates: the calibrator calibrates. */
function CatalogStatus({ catalogState }: { catalogState: CatalogState }) {
  if (catalogState === "loading") return <p role="status">Loading templates...</p>;
  if (catalogState === "error") {
    return <p role="alert">Could not load templates. Reload to try again.</p>;
  }
  return <p>No templates yet -- add a folder of photos under mockup-templates/.</p>;
}

interface TemplateEditorProps {
  templateName: string;
  config: TemplateConfigState;
  session: TemplateSession;
  space: [number, number] | null;
  colours: string[];
  knownColours: string[];
  design: string;
  onDesignChange: (design: string) => void;
  rendererControls: ReactNode;
}

/** The editor for the template's renderer and kind. */
function TemplateEditor({
  templateName,
  config,
  session,
  colours,
  knownColours,
  ...shared
}: TemplateEditorProps) {
  const { preparation } = session;
  const common = { ...shared, templateName, onChange: session.update };
  if (config.renderer.type === "marigold") {
    const recovery = preparation?.maps.reason === "photo_changed";
    return (
      <MarigoldEditor
        key={templateName}
        {...common}
        config={{ ...config, renderer: config.renderer }}
        colours={colours}
        knownColours={knownColours}
        preparation={preparation}
        calibrationRevision={session.calibrationRevision}
        maskEdits={session.maskEdits}
        onMaskEdits={session.setMaskEdits}
        onPreviewPending={session.setPreviewPending}
        savedConfig={session.saved}
        onPrepare={() => void session.prepare(recovery ? "prepare_again" : "prepare", recovery)}
      />
    );
  }
  if (config.renderer.type !== "photo-warp") return null;
  if (config.kind === "colour-matrix") {
    return (
      <ColourMatrixEditor
        key={templateName}
        {...common}
        config={config}
        colours={colours}
        onApprove={() => void session.approve()}
      />
    );
  }
  if (config.kind === "multiple") {
    return (
      <MultipleEditor key={templateName} {...common} config={config} knownColours={knownColours} />
    );
  }
  return <SingleEditor key={templateName} {...common} config={config} />;
}

export function App() {
  const preparationJobs = usePreparationQueue();
  const rendererCache = useRef<Record<string, Partial<Record<Renderer["type"], Renderer>>>>({});
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [catalogState, setCatalogState] = useState<CatalogState>("loading");
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
    const renderer = cache[type] ?? fallbackRenderer(type, preparation?.renderer_settings[type]);
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
              {...runtimeLimits(runtime)}
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
  const isMarigold = config?.renderer.type === "marigold";
  const preparationStatus = preparing ? "Preparing" : preparationLabel(preparation);

  // The photo's true pixel size, which is the coordinate space every bounding
  // box in template.yaml is written in. It has to come from the API: the
  // editors' canvas renders a downscale now, so measuring the image on screen
  // would put the boxes in the preview's space and save them several times too
  // small. `null` for a directory with no readable photo -- there is nothing
  // to calibrate against, and the editors say so rather than guessing.
  const space: [number, number] | null =
    selected?.width && selected.height ? [selected.width, selected.height] : null;

  return (
    <div className={isMarigold ? "app mg-frame mg-app" : "app mg-frame"}>
      <header className="app__header">
        <h1 className="app__title">Mockup Templates</h1>
        {selected && (
          <TemplateCrumb
            selected={selected}
            config={config}
            preparationStatus={preparationStatus}
            statusClass={marigoldStatusClass(preparing, preparation)}
          />
        )}

        <div className="app__actions">
          <p className="app__status" role="status">
            <SaveStatus save={save} load={session.load} catalogState={catalogState} />
          </p>
          {save.kind === "conflict" && <button onClick={session.reload}>Reload template</button>}
        </div>
      </header>

      <div className="app__workbench">
        <TemplateRail
          templates={railTemplates}
          selectedPreparationStatus={isMarigold ? preparationStatus : null}
          selected={templateName}
          onSelect={setTemplateName}
          jobs={preparationJobs}
        />

        <div className="app__workspace">
          {/* 2a: an uncalibrated template replaces the workspace with a single
              choice, so nothing else can be touched yet. Kind decides the
              whole shape of template.yaml (ADR-0014) -- every other control is
              meaningless or wrong until it is answered. */}
          {!templateName && <CatalogStatus catalogState={catalogState} />}
          {templateName && session.load !== "ready" && (
            <p role={session.load === "error" ? "alert" : "status"}>
              {session.load === "error"
                ? "Could not load template configuration. Reload to try again."
                : "Loading template..."}
            </p>
          )}
          {templateName && session.load === "ready" && !config && (
            <KindPicker
              key={templateName}
              templateName={templateName}
              onAssigned={() => {
                session.reload();
                refreshTemplates(templateName);
              }}
            />
          )}
          {templateName && session.load === "ready" && config && (
            <PositionedListingsNote
              templateName={templateName}
              savedAt={save.kind === "saved" ? save.savedAt : null}
            />
          )}
          {templateName && session.load === "ready" && config && (
            <TemplateEditor
              templateName={templateName}
              config={config}
              session={session}
              space={space}
              colours={selected?.colours ?? []}
              knownColours={knownColours}
              design={design}
              onDesignChange={setDesign}
              rendererControls={rendererControls}
            />
          )}
        </div>
      </div>
    </div>
  );
}
