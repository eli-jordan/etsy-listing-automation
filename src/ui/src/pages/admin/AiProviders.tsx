import { useEffect, useRef, useState } from "react";
import { DotsSixVerticalIcon } from "@phosphor-icons/react";
import {
  getModelCatalogs,
  type ModelCatalogs,
  type ProviderPreference,
} from "../../api/workspaceSettings";

const names = ["codex", "claude", "grok"] as const;
const labels = { codex: "Codex", claude: "Claude", grok: "Grok" };
const complete = (initial: ProviderPreference[]): ProviderPreference[] => [
  ...initial,
  ...names
    .filter((name) => !initial.some((p) => p.name === name))
    .map((name) => ({ name, enabled: false })),
];

/** A whole ordered-list edit shares settings.yaml's existing save queue.
 * AiSettingsSections couples an enable with its run floor (ADR-0057).
 */
export function AiProviders({
  initial,
  onSave,
  locked,
}: {
  initial: ProviderPreference[];
  onSave: (providers: ProviderPreference[]) => void;
  locked: boolean;
}) {
  const [rows, setRows] = useState(() => complete(initial));
  const committed = useRef(JSON.stringify(complete(initial)));
  const [blocked, setBlocked] = useState(false);
  const [catalogs, setCatalogs] = useState<ModelCatalogs | null>(null);
  const [busy, setBusy] = useState(true);
  const [problem, setProblem] = useState<string | null>(null);
  const alive = useRef(false);
  const refreshing = useRef(false);
  const drag = useRef<string | null>(null);

  useEffect(() => {
    let active = true;
    alive.current = true;
    getModelCatalogs().then(
      (loaded) => {
        if (active) {
          setCatalogs(loaded);
          setBusy(false);
        }
      },
      (error: unknown) => {
        if (active) {
          setProblem(String(error));
          setBusy(false);
        }
      },
    );
    return () => {
      active = false;
      alive.current = false;
    };
  }, []);

  const refresh = async () => {
    if (refreshing.current) return;
    refreshing.current = true;
    setBusy(true);
    try {
      const loaded = await getModelCatalogs(true);
      if (alive.current) {
        setCatalogs(loaded);
        setProblem(null);
      }
    } catch {
      if (alive.current) setProblem("Could not read the model lists. Saved choices are kept.");
    } finally {
      refreshing.current = false;
      if (alive.current) setBusy(false);
    }
  };
  const commit = (next = rows) => {
    if (locked || JSON.stringify(next) === committed.current) return;
    committed.current = JSON.stringify(next);
    onSave(
      next.map(({ name, enabled, model, effort }) => ({
        name,
        enabled: enabled ?? true,
        ...(model ? { model } : {}),
        ...(effort ? { effort } : {}),
      })),
    );
  };
  const update = (name: string, patch: Partial<ProviderPreference>, save: boolean) => {
    const next = rows.map((row) => (row.name === name ? { ...row, ...patch } : row));
    setRows(next);
    if (save) commit(next);
  };
  const move = (from: number, to: number) => {
    const row = rows[from];
    if (locked || !row || from === to || to < 0 || to >= rows.length) return;
    const next = [...rows];
    next.splice(from, 1);
    next.splice(to, 0, row);
    setRows(next);
    commit(next);
  };
  const count = rows.filter((p) => p.enabled !== false).length;
  const failed = problem || Object.values(catalogs?.providers ?? {}).some((p) => p?.problem);
  let number = 0;
  return (
    <section className="b-panel" aria-labelledby="settings-providers">
      <div className="b-panel__head">
        <div>
          <h2 className="b-panel__title" id="settings-providers">
            AI providers
          </h2>
          <p className="b-panel__lede">
            Each run starts at the top and falls through if a provider is unavailable or rejects its
            saved model or reasoning. Click a number to turn it off, or a dash to turn it on. Drag a
            handle or use its Up/Down keys to reorder. Changes start with the next run.
          </p>
        </div>
      </div>
      <div className="sp-discovery">
        <span role="status">
          {busy
            ? "Checking installed CLIs…"
            : failed
              ? "Model lists unavailable. Saved choices are kept."
              : "Model lists loaded. Cached for 30 minutes."}
        </span>
        <button
          type="button"
          className="btn btn-ghost"
          disabled={busy}
          onClick={() => void refresh()}
        >
          {busy ? "Refreshing…" : "Refresh lists"}
        </button>
      </div>
      {problem && (
        <p className="adm-warn" role="alert">
          {problem}
        </p>
      )}
      {blocked && (
        <p className="adm-warn" role="status">
          At least one provider stays on
        </p>
      )}
      <ol className="b-chain">
        {rows.map((p, index) => {
          const enabled = p.enabled !== false;
          const label = labels[p.name];
          const step = enabled ? ++number : null;
          const catalog = catalogs?.providers?.[p.name];
          const available = !!catalog && !catalog.problem && !problem;
          const models = available ? (catalog.models ?? []) : [];
          const selectedModel = models.find((m) => m.id === p.model);
          const efforts =
            p.name === "codex" && p.model
              ? (selectedModel?.efforts ?? [])
              : available
                ? (catalog.efforts ?? [])
                : [];
          const staleModel = available && !!p.model && !selectedModel;
          const staleEffort = available && !!p.effort && !efforts.includes(p.effort);
          return (
            <li
              key={p.name}
              className={enabled ? "b-step" : "b-step is-off"}
              onDragOver={(event) => {
                if (drag.current) event.preventDefault();
              }}
              onDrop={(event) => {
                event.preventDefault();
                if (drag.current)
                  move(
                    rows.findIndex((row) => row.name === drag.current),
                    index,
                  );
                drag.current = null;
              }}
            >
              <button
                type="button"
                className="b-step__num sp-num"
                aria-pressed={enabled}
                aria-label={
                  enabled ? `${label} is step ${step}. Turn it off` : `${label} is off. Turn it on`
                }
                onClick={() => {
                  if (enabled && count === 1) {
                    setBlocked(true);
                    return;
                  }
                  setBlocked(false);
                  update(p.name, { enabled: !enabled }, true);
                }}
              >
                {step ?? "–"}
              </button>
              <div className="b-step__body">
                <div className="b-step__top">
                  <button
                    type="button"
                    className="adm-handle"
                    draggable={!locked}
                    aria-label={`Move ${label}. Use the up and down arrow keys.`}
                    onDragStart={(event) => {
                      drag.current = p.name;
                      event.dataTransfer.effectAllowed = "move";
                      event.dataTransfer.setData("text/plain", p.name);
                    }}
                    onDragEnd={() => {
                      drag.current = null;
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "ArrowUp" || event.key === "ArrowDown") {
                        event.preventDefault();
                        move(index, index + (event.key === "ArrowUp" ? -1 : 1));
                      }
                    }}
                  >
                    <DotsSixVerticalIcon size={18} />
                  </button>
                  <span className="b-step__name">{label}</span>
                  {!enabled && <span className="b-step__off-note">Off · runs skip it</span>}
                </div>
                {catalog?.problem && (
                  <p className="adm-warn">
                    {catalog.problem} Keep a saved choice or use Account default.
                  </p>
                )}
                {enabled && (
                  <div className="b-step__fields">
                    <div>
                      <label htmlFor={`model-${p.name}`}>{label} model</label>
                      <select
                        id={`model-${p.name}`}
                        className="adm-select"
                        value={p.model ?? ""}
                        onChange={(event) =>
                          update(p.name, { model: event.target.value || null }, false)
                        }
                        onBlur={() => commit()}
                      >
                        <option value="">Account default</option>
                        {p.model && !selectedModel && (
                          <option value={p.model}>{p.model} (saved)</option>
                        )}
                        {models.map((model) => (
                          <option key={model.id} value={model.id}>
                            {model.label}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label htmlFor={`effort-${p.name}`}>{label} reasoning</label>
                      <select
                        id={`effort-${p.name}`}
                        className="adm-select"
                        value={p.effort ?? ""}
                        onChange={(event) =>
                          update(p.name, { effort: event.target.value || null }, false)
                        }
                        onBlur={() => commit()}
                      >
                        <option value="">Account default</option>
                        {p.effort && !efforts.includes(p.effort) && (
                          <option value={p.effort}>{p.effort} (saved)</option>
                        )}
                        {efforts.map((effort) => (
                          <option key={effort} value={effort}>
                            {effort}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                )}
                {staleModel && (
                  <p className="adm-warn" role="status">
                    {p.model} is no longer offered by {label}. Runs still pass it; a rejection moves
                    to the next provider.
                  </p>
                )}
                {staleEffort && (
                  <p className="adm-warn" role="status">
                    {p.effort} is no longer offered for this model. Runs still pass it; a rejection
                    moves to the next provider.
                  </p>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
