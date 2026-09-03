import { useCallback, useEffect, useState } from "react";
import {
  getTemplateConfig,
  listTemplates,
  renderPreview,
  saveTemplateConfig,
} from "./api/calibrator";
import { QuadEditor } from "./components/QuadEditor";
import { ShadeControls, DisplaceControls } from "./components/RenderControls";
import type { Quad, RenderConfigState, TemplateSummary } from "./types";

const DEFAULT_CONFIG: RenderConfigState = {
  warp: {
    quad: [
      [40, 40],
      [360, 40],
      [360, 440],
      [40, 440],
    ],
  },
  displace: { enabled: false, strength: 0 },
  shade: { enabled: true, opacity: 0.6, blend: "soft-light" },
};

const PREVIEW_DEBOUNCE_MS = 200;

export function App() {
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [templateName, setTemplateName] = useState<string | null>(null);
  const [colour, setColour] = useState<string | null>(null);
  const [config, setConfig] = useState<RenderConfigState>(DEFAULT_CONFIG);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [status, setStatus] = useState("");

  useEffect(() => {
    listTemplates()
      .then((loaded) => {
        setTemplates(loaded);
        const first = loaded[0];
        if (first) {
          setTemplateName(first.name);
          setColour(first.colours[0] ?? null);
        }
      })
      .catch(() => setStatus("failed to load templates"));
  }, []);

  useEffect(() => {
    if (!templateName) return;
    // A fresh upload has no template.yaml yet; keep the default quad for it.
    getTemplateConfig(templateName)
      .then((loaded) => setConfig(loaded ?? DEFAULT_CONFIG))
      .catch(() => setStatus("failed to load template config"));
  }, [templateName]);

  // Debounced so a quad drag or slider sweep issues one render per pause,
  // not one per pointer event.
  useEffect(() => {
    if (!templateName || !colour) return;
    const timer = setTimeout(() => {
      renderPreview(templateName, colour, config)
        .then((url) => {
          setPreviewUrl((previous) => {
            if (previous) URL.revokeObjectURL(previous);
            return url;
          });
          setStatus("");
        })
        .catch(() => setStatus(`preview failed for ${colour}`));
    }, PREVIEW_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [templateName, colour, config]);

  const handleQuadChange = useCallback((quad: Quad) => {
    setConfig((current) => ({ ...current, warp: { quad } }));
  }, []);

  const handleSave = useCallback(() => {
    if (!templateName) return;
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
              {t.name}
            </option>
          ))}
        </select>
      </header>

      {selected && (
        <div className="app__filmstrip">
          {selected.colours.map((c) => (
            <button
              key={c}
              className={
                c === colour ? "filmstrip__item filmstrip__item--active" : "filmstrip__item"
              }
              onClick={() => setColour(c)}
            >
              {c}
            </button>
          ))}
        </div>
      )}

      <main className="app__main">
        <div className="app__preview">
          {previewUrl ? (
            <QuadEditor imageUrl={previewUrl} quad={config.warp.quad} onChange={handleQuadChange} />
          ) : (
            <p>Select a template to preview.</p>
          )}
        </div>

        <aside className="app__controls">
          <DisplaceControls
            value={config.displace}
            onChange={(displace) => setConfig((c) => ({ ...c, displace }))}
          />
          <ShadeControls
            value={config.shade}
            onChange={(shade) => setConfig((c) => ({ ...c, shade }))}
          />
          <button onClick={handleSave}>Save template.yaml</button>
          <p className="app__status" role="status">
            {status}
          </p>
        </aside>
      </main>
    </div>
  );
}
