import { useCallback, useEffect, useState } from "react";
import { getTemplateConfig, listTemplates, saveTemplateConfig } from "./api/calibrator";
import { UploadForm } from "./components/UploadForm";
import { ColourMatrixEditor } from "./editors/ColourMatrixEditor";
import { MultipleEditor } from "./editors/MultipleEditor";
import { SingleEditor } from "./editors/SingleEditor";
import type { TemplateConfigState, TemplateSummary } from "./types";

/** A thin router: loads the selected template's config and picks an editor
 * by `kind` -- a template.yaml is exactly one of three shapes, never a mix. */
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
  const [status, setStatus] = useState("");

  const refreshTemplates = useCallback((selectName?: string) => {
    listTemplates()
      .then((loaded) => {
        setTemplates(loaded);
        setTemplateName((current) => selectName ?? current ?? loaded[0]?.name ?? null);
      })
      .catch(() => setStatus("failed to load templates"));
  }, []);

  useEffect(() => {
    refreshTemplates();
  }, [refreshTemplates]);

  useEffect(() => {
    if (!templateName) return;
    getTemplateConfig(templateName)
      .then((loaded) => setConfigEntry(loaded ? { name: templateName, config: loaded } : null))
      .catch(() => setStatus("failed to load template config"));
  }, [templateName]);

  const config = configEntry?.name === templateName ? configEntry.config : null;

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
      .then(() => setStatus("saved"))
      .catch(() => setStatus("save failed"));
  }, [templateName, config]);

  const selected = templates.find((t) => t.name === templateName);

  return (
    <div className="app">
      <header className="app__header">
        <h1>Mockup calibrator</h1>
        <select
          aria-label="Template"
          value={templateName ?? ""}
          onChange={(e) => setTemplateName(e.target.value || null)}
        >
          {templates.map((t) => (
            <option key={t.name} value={t.name}>
              {t.name} {t.kind ? `(${t.kind})` : "(unconfigured)"}
            </option>
          ))}
        </select>
        <button className="btn btn-primary" onClick={handleSave} disabled={!config}>
          Save template.yaml
        </button>
        <p className="app__status" role="status">
          {status}
        </p>
      </header>

      {templateName && config?.kind === "colour-matrix" && (
        <ColourMatrixEditor
          templateName={templateName}
          config={config}
          colours={selected?.colours ?? []}
          onChange={setConfig}
        />
      )}
      {templateName && config?.kind === "multiple" && (
        <MultipleEditor templateName={templateName} config={config} onChange={setConfig} />
      )}
      {templateName && config?.kind === "single" && (
        <SingleEditor templateName={templateName} config={config} onChange={setConfig} />
      )}
      {templateName && !config && <p>No template.yaml yet for {templateName}.</p>}
      {!templateName && <p>No templates yet -- upload one below.</p>}

      <UploadForm onUploaded={(name) => refreshTemplates(name)} />
    </div>
  );
}
