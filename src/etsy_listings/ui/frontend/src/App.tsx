import { useEffect, useState } from "react";
import { api } from "./api/client";
import { QuadEditor } from "./components/QuadEditor";
import type { RenderConfigState, ShadeBlend, TemplateSummary } from "./types";

const DEFAULT_QUAD: RenderConfigState["warp"]["quad"] = [
  [40, 40],
  [360, 40],
  [360, 440],
  [40, 440],
];

const DEFAULT_CONFIG: RenderConfigState = {
  warp: { quad: DEFAULT_QUAD },
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
  const [status, setStatus] = useState<string>("");

  useEffect(() => {
    void refreshTemplates();
  }, []);

  useEffect(() => {
    if (!templateName) return;
    void loadConfig(templateName);
  }, [templateName]);

  useEffect(() => {
    if (!templateName || !colour) return;
    const timer = setTimeout(() => {
      void fetchPreview(templateName, colour, config);
    }, PREVIEW_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [templateName, colour, config]);

  async function refreshTemplates() {
    const { data, error } = await api.GET("/api/templates");
    if (error) {
      setStatus("failed to load templates");
      return;
    }
    setTemplates(data);
    const first = data[0];
    if (first) {
      setTemplateName(first.name);
      setColour(first.colours[0] ?? null);
    }
  }

  async function loadConfig(name: string) {
    const { data, error } = await api.GET("/api/templates/{name}/config", {
      params: { path: { name } },
    });
    if (error) {
      // No template.yaml yet (a freshly-uploaded set) -- keep the default quad.
      return;
    }
    setConfig(data);
  }

  async function fetchPreview(name: string, colourName: string, cfg: RenderConfigState) {
    const response = await fetch(`/api/templates/${encodeURIComponent(name)}/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ colour: colourName, ...cfg }),
    });
    if (!response.ok) {
      setStatus(`preview failed for ${colourName}`);
      return;
    }
    const blob = await response.blob();
    setPreviewUrl((old) => {
      if (old) URL.revokeObjectURL(old);
      return URL.createObjectURL(blob);
    });
    setStatus("");
  }

  async function save() {
    if (!templateName) return;
    const { error } = await api.PUT("/api/templates/{name}/config", {
      params: { path: { name: templateName } },
      body: config,
    });
    setStatus(error ? "save failed" : "saved");
  }

  const selected = templates.find((t) => t.name === templateName);

  return (
    <div className="app">
      <header className="app__header">
        <h1>Mockup calibrator</h1>
        <select
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
            <QuadEditor
              imageUrl={previewUrl}
              quad={config.warp.quad}
              onChange={(quad) => setConfig((c) => ({ ...c, warp: { quad } }))}
            />
          ) : (
            <p>Select a template to preview.</p>
          )}
        </div>

        <aside className="app__controls">
          <fieldset>
            <legend>Displace</legend>
            <label>
              <input
                type="checkbox"
                checked={config.displace.enabled}
                onChange={(e) =>
                  setConfig((c) => ({
                    ...c,
                    displace: { ...c.displace, enabled: e.target.checked },
                  }))
                }
              />
              enabled
            </label>
            <label>
              strength
              <input
                type="range"
                min={0}
                max={1}
                step={0.01}
                value={config.displace.strength}
                onChange={(e) =>
                  setConfig((c) => ({
                    ...c,
                    displace: { ...c.displace, strength: Number(e.target.value) },
                  }))
                }
              />
            </label>
          </fieldset>

          <fieldset>
            <legend>Shade</legend>
            <label>
              <input
                type="checkbox"
                checked={config.shade.enabled}
                onChange={(e) =>
                  setConfig((c) => ({ ...c, shade: { ...c.shade, enabled: e.target.checked } }))
                }
              />
              enabled
            </label>
            <label>
              opacity
              <input
                type="range"
                min={0}
                max={1}
                step={0.01}
                value={config.shade.opacity}
                onChange={(e) =>
                  setConfig((c) => ({
                    ...c,
                    shade: { ...c.shade, opacity: Number(e.target.value) },
                  }))
                }
              />
            </label>
            <label>
              blend
              <select
                value={config.shade.blend}
                onChange={(e) =>
                  setConfig((c) => ({
                    ...c,
                    shade: { ...c.shade, blend: e.target.value as ShadeBlend },
                  }))
                }
              >
                <option value="soft-light">soft-light</option>
                <option value="multiply">multiply</option>
                <option value="grey-pivot">grey-pivot</option>
              </select>
            </label>
          </fieldset>

          <button onClick={() => void save()}>Save template.yaml</button>
          <p className="app__status">{status}</p>
        </aside>
      </main>
    </div>
  );
}
