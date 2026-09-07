import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getTemplateConfig, listTemplates, saveTemplateConfig } from "./api/calibrator";
import { KindPicker } from "./components/KindPicker";
import { TemplateRail } from "./components/TemplateRail";
import { ColourMatrixEditor } from "./editors/ColourMatrixEditor";
import { MultipleEditor } from "./editors/MultipleEditor";
import { SingleEditor } from "./editors/SingleEditor";
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
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [templateName, setTemplateName] = useState<string | null>(null);
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
  const [status, setStatus] = useState("");
  // Which test artwork the previews render with (A19). A way of looking at a
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
        const entry = loaded ? { name: templateName, config: loaded } : null;
        setConfigEntry(entry);
        setSavedEntry(entry);
      })
      .catch(() => {
        if (current) setStatus("failed to load template config");
      });
    return () => {
      current = false;
    };
  }, [templateName, configVersion]);

  const config = configEntry?.name === templateName ? configEntry.config : null;
  const saved = savedEntry?.name === templateName ? savedEntry.config : null;

  const dirty = useMemo(
    () => config !== null && saved !== null && JSON.stringify(config) !== JSON.stringify(saved),
    [config, saved],
  );

  const setConfig = useCallback(
    (next: TemplateConfigState) => {
      if (!templateName) return;
      setConfigEntry({ name: templateName, config: next });
    },
    [templateName],
  );

  const handleSave = useCallback(() => {
    if (!templateName || !config) return;
    saveTemplateConfig(templateName, config)
      .then(() => {
        setSavedEntry({ name: templateName, config });
        setStatus("saved");
        // The save may have changed whether this template still counts as
        // needing calibration, and the rail is what shows that.
        refreshTemplates(templateName);
      })
      .catch(() => setStatus("save failed"));
  }, [templateName, config, refreshTemplates]);

  const handleReset = useCallback(() => {
    if (!templateName || !saved) return;
    setConfigEntry({ name: templateName, config: saved });
    setStatus("reset");
  }, [templateName, saved]);

  const selected = templates.find((t) => t.name === templateName);

  // Every colour already in use anywhere in the workspace, for the box
  // colour field's suggestions. Suggestions rather than a closed list: a
  // chart's colours are whatever the listing sells, and nothing here knows
  // that -- wiring in the Printify catalog would be a much larger dependency.
  const knownColours = useMemo(
    () => [...new Set(templates.flatMap((t) => t.colours))].filter(Boolean).sort(),
    [templates],
  );
  const kindLabel = selected?.kind ? KIND_LABELS[selected.kind] : null;

  return (
    <div className="app">
      <header className="app__header">
        <h1 className="app__title">Mockup calibrator</h1>
        {selected && (
          <>
            <span className="app__crumb-sep">/</span>
            <span className="app__crumb">{selected.name}</span>
            <span
              className={selected.status === "calibrated" ? "tag tag-accent-2" : "tag tag-accent"}
            >
              {selected.status === "calibrated" ? "calibrated" : "needs calibration"}
            </span>
            <span className="app__meta">
              {selected.status === "calibrated"
                ? `${kindLabel ?? "Unknown"} · ${selected.colours.length} colour${
                    selected.colours.length === 1 ? "" : "s"
                  }`
                : (selected.status_reason ?? "not calibrated")}
            </span>
          </>
        )}

        <div className="app__actions">
          <p className="app__status" role="status">
            {status}
          </p>
          <button onClick={handleReset} disabled={!dirty}>
            Reset
          </button>
          <button className="btn btn-primary" onClick={handleSave} disabled={!config}>
            Save template.yaml
          </button>
        </div>
      </header>

      <div className="app__workbench">
        <TemplateRail templates={templates} selected={templateName} onSelect={setTemplateName} />

        <div className="app__workspace">
          {/* 2a: an uncalibrated template replaces the workspace with a single
              choice, so nothing else can be touched yet. Kind decides the
              whole shape of template.yaml (A11) -- every other control is
              meaningless or wrong until it is answered. */}
          {templateName && !config ? (
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
              {templateName && config?.kind === "colour-matrix" && (
                <ColourMatrixEditor
                  templateName={templateName}
                  config={config}
                  colours={selected?.colours ?? []}
                  onChange={setConfig}
                  design={design}
                  onDesignChange={setDesign}
                  onApprove={handleSave}
                />
              )}
              {templateName && config?.kind === "multiple" && (
                <MultipleEditor
                  templateName={templateName}
                  config={config}
                  onChange={setConfig}
                  design={design}
                  onDesignChange={setDesign}
                  knownColours={knownColours}
                />
              )}
              {templateName && config?.kind === "single" && (
                <SingleEditor
                  templateName={templateName}
                  config={config}
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
