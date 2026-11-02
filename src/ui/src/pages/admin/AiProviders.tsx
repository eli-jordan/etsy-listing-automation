import { useEffect, useRef, useState } from "react";
import { DotsSixVerticalIcon } from "@phosphor-icons/react/dist/csr/DotsSixVertical";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import {
  getModelCatalogs,
  type ModelCatalogs,
  type ProviderPreference,
} from "../../api/workspaceSettings";
import type { components } from "../../api/schema";

type ProviderCatalog = components["schemas"]["ProviderCatalog"];
type ModelChoice = components["schemas"]["ModelChoice"];

const names = ["codex", "claude", "grok"] as const;
type ProviderName = (typeof names)[number];
const labels = { codex: "Codex", claude: "Claude", grok: "Grok" };
const sources = {
  codex: "from codex debug models",
  claude: "curated list",
  grok: "from grok models",
};
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
  const [problem, setProblem] = useState(false);
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
      () => {
        if (active) {
          setProblem(true);
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
        setProblem(false);
      }
    } catch {
      if (alive.current) setProblem(true);
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
  // One notice when nothing could be read; per-row problems only when some CLIs answered.
  const allFailed = problem || (!!catalogs && names.every((n) => catalogs.providers?.[n]?.problem));
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
        <span role="status">{discoveryStatus(busy, failed)}</span>
        <button
          type="button"
          className="btn btn-ghost"
          disabled={busy}
          onClick={() => void refresh()}
        >
          {busy ? "Refreshing…" : "Refresh lists"}
        </button>
      </div>
      {allFailed && (
        <p className="adm-warn" role="alert">
          <WarningIcon size={16} />
          <span>
            Could not read the model lists. You can keep a saved choice or use Account default.
            Refresh to try again.
          </span>
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
          return (
            <ProviderRow
              key={p.name}
              preference={p}
              step={enabled ? ++number : null}
              catalog={catalogs?.providers?.[p.name]}
              problem={problem}
              allFailed={allFailed}
              locked={locked}
              onToggle={() => {
                if (enabled && count === 1) {
                  setBlocked(true);
                  return;
                }
                setBlocked(false);
                update(p.name, { enabled: !enabled }, true);
              }}
              onChange={(patch) => update(p.name, patch, false)}
              onCommit={() => commit()}
              drag={{
                start: () => {
                  drag.current = p.name;
                },
                end: () => {
                  drag.current = null;
                },
                drop: () => {
                  if (drag.current)
                    move(
                      rows.findIndex((row) => row.name === drag.current),
                      index,
                    );
                  drag.current = null;
                },
                active: () => drag.current !== null,
                move: (by) => move(index, index + by),
              }}
            />
          );
        })}
      </ol>
    </section>
  );
}

function discoveryStatus(busy: boolean, failed: boolean): string {
  if (busy) return "Checking installed CLIs…";
  if (failed) return "Model lists unavailable. Saved choices are kept.";
  return "Model lists loaded. Cached for 30 minutes.";
}

type Choices = {
  models: ModelChoice[];
  selectedModel: ModelChoice | undefined;
  efforts: string[];
  staleModel: boolean;
  staleEffort: boolean;
};

/** What a row offers, and whether its saved choices are still among them. */
function choicesFor(
  p: ProviderPreference,
  catalog: ProviderCatalog | undefined,
  problem: boolean,
): Choices {
  const available = !!catalog && !catalog.problem && !problem;
  const models = available ? (catalog.models ?? []) : [];
  const selectedModel = models.find((m) => m.id === p.model);
  let efforts: string[] = [];
  if (p.name === "codex" && p.model) efforts = selectedModel?.efforts ?? [];
  else if (available) efforts = catalog.efforts ?? [];
  return {
    models,
    selectedModel,
    efforts,
    staleModel: available && !!p.model && !selectedModel,
    staleEffort: available && !!p.effort && !efforts.includes(p.effort),
  };
}

type RowDrag = {
  start: () => void;
  end: () => void;
  drop: () => void;
  active: () => boolean;
  move: (by: number) => void;
};

function ProviderRow({
  preference: p,
  step,
  catalog,
  problem,
  allFailed,
  locked,
  onToggle,
  onChange,
  onCommit,
  drag,
}: {
  preference: ProviderPreference;
  step: number | null;
  catalog: ProviderCatalog | undefined;
  problem: boolean;
  allFailed: boolean;
  locked: boolean;
  onToggle: () => void;
  onChange: (patch: Partial<ProviderPreference>) => void;
  onCommit: () => void;
  drag: RowDrag;
}) {
  const enabled = step !== null;
  const name = p.name as ProviderName;
  const label = labels[name];
  const { models, selectedModel, efforts, staleModel, staleEffort } = choicesFor(
    p,
    catalog,
    problem,
  );
  return (
    <li
      className={enabled ? "b-step" : "b-step is-off"}
      onDragOver={(event) => {
        if (drag.active()) event.preventDefault();
      }}
      onDrop={(event) => {
        event.preventDefault();
        drag.drop();
      }}
    >
      <button
        type="button"
        className="b-step__num sp-num"
        aria-pressed={enabled}
        aria-label={
          enabled ? `${label} is step ${step}. Turn it off` : `${label} is off. Turn it on`
        }
        onClick={onToggle}
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
              drag.start();
              event.dataTransfer.effectAllowed = "move";
              event.dataTransfer.setData("text/plain", p.name);
            }}
            onDragEnd={drag.end}
            onKeyDown={(event) => {
              if (event.key === "ArrowUp" || event.key === "ArrowDown") {
                event.preventDefault();
                drag.move(event.key === "ArrowUp" ? -1 : 1);
              }
            }}
          >
            <DotsSixVerticalIcon size={18} />
          </button>
          <span className="b-step__name">{label}</span>
          <span className="b-step__spacer" />
          {!enabled && <span className="b-step__off-note">Off — runs skip it</span>}
        </div>
        {catalog?.problem && !allFailed && (
          <p className="adm-warn">
            <WarningIcon size={16} />
            <span>{catalog.problem} Keep a saved choice or use Account default.</span>
          </p>
        )}
        {enabled && (
          <div className="b-step__fields">
            <ChoiceSelect
              id={`model-${p.name}`}
              label={`Model · ${sources[name]}`}
              ariaLabel={`${label} model`}
              saved={p.model}
              offered={!!selectedModel}
              stale={staleModel}
              options={models.map((model) => ({ value: model.id, label: model.label }))}
              onChange={(value) => onChange({ model: value })}
              onCommit={onCommit}
            />
            <ChoiceSelect
              id={`effort-${p.name}`}
              label="Reasoning"
              ariaLabel={`${label} reasoning`}
              saved={p.effort}
              offered={!!p.effort && efforts.includes(p.effort)}
              stale={staleEffort}
              options={efforts.map((effort) => ({ value: effort, label: effort }))}
              onChange={(value) => onChange({ effort: value })}
              onCommit={onCommit}
            />
          </div>
        )}
        {staleModel && (
          <p className="adm-warn" role="status">
            <WarningIcon size={15} />
            <span>
              {p.model} is no longer offered by the {label} CLI. Runs still pass it; if {label}{" "}
              refuses it, the chain moves on.
            </span>
          </p>
        )}
        {staleEffort && (
          <p className="adm-warn" role="status">
            <WarningIcon size={15} />
            <span>
              {p.effort} is no longer offered for this model. Runs still pass it; if {label} refuses
              it, the chain moves on.
            </span>
          </p>
        )}
      </div>
    </li>
  );
}

/** One model or reasoning picker. A saved value the list no longer offers stays selectable. */
function ChoiceSelect({
  id,
  label,
  ariaLabel,
  saved,
  offered,
  stale,
  options,
  onChange,
  onCommit,
}: {
  id: string;
  label: string;
  ariaLabel: string;
  saved: string | null | undefined;
  offered: boolean;
  stale: boolean;
  options: { value: string; label: string }[];
  onChange: (value: string | null) => void;
  onCommit: () => void;
}) {
  return (
    <div>
      <label htmlFor={id}>{label}</label>
      <select
        id={id}
        aria-label={ariaLabel}
        className={stale ? "adm-select adm-select--invalid" : "adm-select"}
        value={saved ?? ""}
        onChange={(event) => onChange(event.target.value || null)}
        onBlur={onCommit}
      >
        <option value="">Account default</option>
        {saved && !offered && (
          <option value={saved}>{stale ? `${saved} (not offered)` : saved}</option>
        )}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
