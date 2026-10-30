// The Settings tab of the clickable Admin prototype: round 1's direction B
// (provider fallback chain, batch slider) with market weights as one bar whose
// dividers are dragged instead of typed.
import { ArrowCounterClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowCounterClockwise";
import { DotsSixVerticalIcon } from "@phosphor-icons/react/dist/csr/DotsSixVertical";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { useEffect, useRef, useState, type Dispatch, type SetStateAction, type KeyboardEvent, type PointerEvent } from "react";
import { providers as startProviders, weights as startWeights, type ProviderRow } from "../admin-settings/_fixtures";
import { SaveStatus, StatusDot } from "./_parts";

const SEG = [
  "var(--color-accent-600)",
  "var(--color-accent-400)",
  "var(--color-accent-2-600)",
  "var(--color-accent-2-400)",
  "var(--color-neutral-600)",
  "var(--color-neutral-400)",
];

export type Scenario = "limits" | "raised" | "discovery" | "conflict" | "invalid" | "disconnected" | "offline";
type Panel = "ai" | "limits" | "batch" | "market";

/** Saving… then Saved, per panel. */
function useSaves() {
  const [state, setState] = useState<Record<Panel, "saved" | "saving">>({ ai: "saved", limits: "saved", batch: "saved", market: "saved" });
  const timers = useRef<Partial<Record<Panel, number>>>({});
  useEffect(() => () => Object.values(timers.current).forEach((t) => window.clearTimeout(t)), []);
  const save = (p: Panel) => {
    setState((s) => ({ ...s, [p]: "saving" }));
    window.clearTimeout(timers.current[p]);
    timers.current[p] = window.setTimeout(() => setState((s) => ({ ...s, [p]: "saved" })), 700);
  };
  return [state, save] as const;
}

export function SettingsPanel({ scrollTo, scenario }: { scrollTo?: "market"; scenario?: Scenario }) {
  const [saves, save] = useSaves();
  const [issue, setIssue] = useState(scenario === "conflict" || scenario === "invalid" ? scenario : null);
  const [config, setConfig] = useState(() => ({
    rows: startProviders.map((p) => ({ ...p, enabled: scenario === "raised" ? true : p.enabled })),
    step: scenario === "raised" ? 10 : 5,
    run: scenario === "raised" ? 30 : 20,
  }));
  const [notice, setNotice] = useState(scenario === "raised" ? "Run limit increased from 20 to 30 minutes to allow 3 providers × 10 minutes." : "");
  const enabled = config.rows.filter((r) => r.enabled).length;
  const floor = Math.max(5, enabled * config.step);
  const setRows: Dispatch<SetStateAction<ProviderRow[]>> = (change) => {
    const rows = typeof change === "function" ? change(config.rows) : change;
    const minimum = Math.max(5, rows.filter((r) => r.enabled).length * config.step);
    if (minimum > config.run) setNotice(`Run limit increased from ${config.run} to ${minimum} minutes because another provider is on.`);
    setConfig({ ...config, rows, run: Math.max(config.run, minimum) });
  };
  const scroller = useRef<HTMLDivElement>(null);
  const marketRef = useRef<HTMLElement>(null);
  const limitsRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const target = scrollTo === "market" ? marketRef.current : scenario === "limits" || scenario === "raised" ? limitsRef.current : null;
    if (target && scroller.current) scroller.current.scrollTop = target.offsetTop;
  }, [scrollTo, scenario]);

  if (issue === "invalid") return (
    <section className="b-panel" aria-labelledby="sp-invalid">
      <h2 className="b-panel__title" id="sp-invalid">Settings could not be loaded</h2>
      <div className="adm-warn sp-notice" role="alert">
        <WarningIcon size={20} />
        <div><strong>ai.run_limit_minutes is too low</strong><p>settings.yaml has 5 minutes. With 2 providers and a 5-minute step limit, it must be at least 10.</p></div>
      </div>
      <p className="b-panel__lede">Correct that key in settings.yaml, then check again. Your file has not been changed.</p>
      <button type="button" className="btn btn-primary" onClick={() => setIssue(null)}>Check file again</button>
      <p className="sp-prototype-note">Prototype: checking again simulates the corrected file.</p>
    </section>
  );

  return (
    <div ref={scroller} className="sp-settings-scroll">
      {issue === "conflict" && <div className="adm-warn sp-notice" role="alert">
        <WarningIcon size={20} />
        <div><strong>Settings changed on disk</strong><p>This save was refused. Reload to read the current file, then make your change again.</p>
          <button type="button" className="btn btn-primary" onClick={() => { setConfig({ rows: startProviders, step: 5, run: 20 }); setIssue(null); }}>Reload settings</button>
        </div>
      </div>}
      <fieldset className="sp-settings-fields" disabled={issue === "conflict"}>
      <Providers rows={config.rows} setRows={setRows} discoveryFailed={scenario === "discovery"} status={saves.ai} onSave={() => { save("ai"); save("limits"); }} />
      <TimeLimits ref_={limitsRef} step={config.step} run={config.run} enabled={enabled} floor={floor} notice={notice} status={saves.limits}
        onChange={(step, run) => {
          const minimum = Math.max(5, enabled * step);
          setNotice(minimum > run ? `Run limit increased from ${run} to ${minimum} minutes to allow ${enabled} providers × ${step} minutes.` : "");
          setConfig({ ...config, step, run: Math.max(run, minimum) });
        }} onSave={() => save("limits")} />
      <Batch status={saves.batch} onSave={() => save("batch")} />
      <Market ref_={marketRef} status={saves.market} onSave={() => save("market")} />
      </fieldset>
    </div>
  );
}

// ------------------------------------------------------------- providers

function Providers({ rows, setRows, discoveryFailed, status, onSave }: {
  rows: ProviderRow[];
  setRows: Dispatch<SetStateAction<ProviderRow[]>>;
  discoveryFailed: boolean;
  status: "saved" | "saving";
  onSave: () => void;
}) {
  const [failed, setFailed] = useState(discoveryFailed);
  const [refresh, setRefresh] = useState<"cached" | "loading" | "fresh">("cached");
  const refreshTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(refreshTimer.current), []);
  const [drag, setDrag] = useState<number | null>(null);
  const [over, setOver] = useState<number | null>(null);
  const [blocked, setBlocked] = useState<string | null>(null);
  const onCount = rows.filter((r) => r.enabled).length;

  const update = (id: string, patch: Partial<ProviderRow>, commit = true) => {
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...patch } : r)));
    if (commit) onSave();
  };
  const move = (from: number, to: number) => {
    if (from === to || to < 0 || to >= rows.length) return;
    setRows((rs) => {
      const next = [...rs];
      const [r] = next.splice(from, 1);
      next.splice(to, 0, r);
      return next;
    });
    onSave();
  };
  const onHandleKey = (e: KeyboardEvent, i: number) => {
    if (e.key === "ArrowUp") {
      e.preventDefault();
      move(i, i - 1);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      move(i, i + 1);
    }
  };

  // Enabled providers are numbered in run order; switched-off ones get a dash.
  let n = 0;
  return (
    <section className="b-panel" aria-labelledby="sp-ai">
      <div className="b-panel__head">
        <div>
          <h2 className="b-panel__title" id="sp-ai">AI providers</h2>
          <p className="b-panel__lede">
            Each run starts at the top and falls through if a provider is unavailable or rejects its saved model. Click a
            step's number to turn it off, or its dash to turn it back on. Drag a step by its handle to reorder.
          </p>
        </div>
        <SaveStatus state={status} />
      </div>
      <div className="sp-discovery">
        <span role="status">{refresh === "loading" ? "Checking installed CLIs…" : failed ? "Model lists unavailable. Saved choices are kept." : refresh === "fresh" ? "Lists refreshed just now · cached for 30 minutes" : "Lists loaded at server start · cached for 30 minutes"}</span>
        <button type="button" className="btn btn-ghost" disabled={refresh === "loading"} onClick={() => {
          setRefresh("loading");
          refreshTimer.current = window.setTimeout(() => { setFailed(false); setRefresh("fresh"); }, 800);
        }}>{refresh === "loading" ? "Refreshing…" : "Refresh lists"}</button>
      </div>
      {failed && <div className="adm-warn" role="alert"><WarningIcon size={16} /><span>Could not read the model lists. You can keep a saved choice or use Account default. Refresh to try again.</span></div>}
      <ol className="b-chain">
        {rows.map((p, i) => {
          const num = p.enabled ? ++n : null;
          const known = p.models.some((m) => m.id === p.model);
          const models = failed ? p.models.filter((m) => m.id === "" || m.id === p.model) : p.models;
          const last = p.enabled && onCount === 1;
          return (
            <li
              key={p.id}
              className={[p.enabled ? "b-step" : "b-step is-off", drag === i ? "sp-dragging" : "", over === i && drag !== i ? "sp-over" : ""].join(" ")}
              draggable={drag === i}
              onDragStart={(e) => {
                e.dataTransfer.effectAllowed = "move";
                e.dataTransfer.setData("text/plain", p.id);
              }}
              onDragOver={(e) => {
                if (drag === null) return;
                e.preventDefault();
                setOver(i);
              }}
              onDrop={(e) => {
                e.preventDefault();
                if (drag !== null) move(drag, i);
                setDrag(null);
                setOver(null);
              }}
              onDragEnd={() => {
                setDrag(null);
                setOver(null);
              }}
            >
              <button
                type="button"
                className="b-step__num sp-num"
                aria-pressed={p.enabled}
                aria-label={p.enabled ? `${p.name} is step ${num}. Turn it off` : `${p.name} is off. Turn it on`}
                title={p.enabled ? "Click to turn off" : "Click to turn on"}
                onClick={() => {
                  if (last) {
                    setBlocked(p.id);
                    return;
                  }
                  setBlocked(null);
                  update(p.id, { enabled: !p.enabled });
                }}
              >
                <span className="sp-num__value">{num ?? "–"}</span>
                <span className="sp-num__hover" aria-hidden="true">
                  {p.enabled ? "–" : "+"}
                </span>
              </button>
              <div className="b-step__body">
                <div className="b-step__top" style={p.enabled ? undefined : { marginBottom: 0 }}>
                  <button
                    type="button"
                    className="adm-handle"
                    aria-label={`Move ${p.name}. Use the up and down arrow keys.`}
                    onPointerDown={() => setDrag(i)}
                    onPointerUp={() => setDrag((d) => (d === i ? null : d))}
                    onKeyDown={(e) => onHandleKey(e, i)}
                  >
                    <DotsSixVerticalIcon size={18} />
                  </button>
                  <span className="b-step__name">{p.name}</span>
                  <StatusDot status={p.status} text={p.statusText} />
                  <span className="b-step__spacer" />
                  {!p.enabled && <span className="b-step__off-note">Off — runs skip it</span>}
                  {last && blocked === p.id && (
                    <span className="b-step__off-note" role="status">
                      At least one provider stays on
                    </span>
                  )}
                </div>
                {p.enabled && (
                  <div className="b-step__fields">
                    <div>
                      <label htmlFor={`sp-model-${p.id}`}>Model · {p.source.toLowerCase()}</label>
                      <select
                        id={`sp-model-${p.id}`}
                        className={known ? "adm-select" : "adm-select adm-select--invalid"}
                        value={p.model}
                        onChange={(e) => update(p.id, { model: e.target.value }, false)}
                        onBlur={onSave}
                      >
                        {!known && <option value={p.model}>{p.model} (not offered)</option>}
                        {models.map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.label}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label htmlFor={`sp-effort-${p.id}`}>Reasoning</label>
                      <select
                        id={`sp-effort-${p.id}`}
                        className="adm-select"
                        value={p.effort}
                        onChange={(e) => update(p.id, { effort: e.target.value }, false)}
                        onBlur={onSave}
                      >
                        {p.efforts.map((x) => (
                          <option key={x} value={x}>
                            {x}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                )}
                {!known && (
                  <div className="adm-warn" style={{ marginTop: "var(--space-3)" }}>
                    <WarningIcon size={15} />
                    <span>
                      {p.model} is no longer offered by the {p.name} CLI. Runs still pass it; if {p.name} refuses it, the
                      chain moves on.
                    </span>
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function TimeLimits({ ref_, step, run, enabled, floor, notice, status, onChange, onSave }: {
  ref_: React.RefObject<HTMLElement>;
  step: number; run: number; enabled: number; floor: number; notice: string;
  status: "saved" | "saving";
  onChange: (step: number, run: number) => void;
  onSave: () => void;
}) {
  const committed = useRef(`${step}/${run}`);
  const commit = () => {
    const next = `${step}/${run}`;
    if (next !== committed.current) { committed.current = next; onSave(); }
  };
  return <section ref={ref_} className="b-panel" aria-labelledby="sp-limits">
    <div className="b-panel__head"><div>
      <h2 className="b-panel__title" id="sp-limits">AI time limits</h2>
      <p className="b-panel__lede">Applies to every AI run, including briefs, market queries and batch drafts. Changes start with the next run.</p>
    </div><SaveStatus state={status} /></div>
    <div className="sp-limits">
      <div className="sp-slider">
        <label className="sp-slider__value" htmlFor="sp-step-limit">Per step <strong>{step} min</strong></label>
        <p className="sp-limit-hint">One provider attempt and its repair share this time. A fallback provider gets a fresh allowance.</p>
        <input id="sp-step-limit" type="range" min={1} max={15} step={1} value={step} aria-valuetext={`${step} minutes per step`}
          style={{ ["--sp-fill" as string]: `${((step - 1) / 14) * 100}%` }}
          onChange={(e) => onChange(Number(e.target.value), run)} onPointerUp={commit} onKeyUp={commit} onBlur={commit} />
        <div className="sp-slider__ticks"><span>1 min</span><span>15 min</span></div>
      </div>
      <div className="sp-slider">
        <label className="sp-slider__value" htmlFor="sp-run-limit">Whole run <strong>{run} min</strong></label>
        <p className="sp-limit-hint">The upper bound for all attempts and research together. Running jobs keep their current limit.</p>
        <input id="sp-run-limit" type="range" min={floor} max={60} step={1} value={run} aria-valuetext={`${run} minutes for the whole run; minimum ${floor}`}
          style={{ ["--sp-fill" as string]: `${((run - floor) / (60 - floor)) * 100}%` }}
          onChange={(e) => onChange(step, Number(e.target.value))} onPointerUp={commit} onKeyUp={commit} onBlur={commit} />
        <div className="sp-slider__ticks"><span>{floor} min</span><span>60 min</span></div>
      </div>
    </div>
    <p className="sp-floor">Minimum whole run: <strong>{floor} minutes</strong> with {enabled} enabled {enabled === 1 ? "provider" : "providers"} × {step} minutes per step{enabled * step < 5 ? " (5-minute minimum)" : ""}.</p>
    {notice && <div className="adm-warn sp-notice" role="status"><WarningIcon size={18} /><span>{notice} Both values save together.</span></div>}
    <p className="sp-limit-hint">Turning a provider off or lowering the step limit leaves your whole-run limit where you set it.</p>
  </section>;
}

// ----------------------------------------------------------------- batch

function Batch({ status, onSave }: { status: "saved" | "saving"; onSave: () => void }) {
  const [value, setValue] = useState(2);
  const committed = useRef(2);
  const commit = () => {
    if (value !== committed.current) {
      committed.current = value;
      onSave();
    }
  };

  return (
    <section className="b-panel" aria-labelledby="sp-batch">
      <div className="b-panel__head">
        <div>
          <h2 className="b-panel__title" id="sp-batch">Batch AI</h2>
          <p className="b-panel__lede">
            How many listings in a batch are drafted at the same time, across all batches. Editor runs don't count.
            Lowering it lets drafts already running finish.
          </p>
        </div>
        <SaveStatus state={status} />
      </div>
      <div className="sp-slider">
        <span className="sp-slider__value" aria-hidden="true">
          <strong>{value}</strong> {value === 1 ? "listing" : "listings"} at once
        </span>
        <input
          type="range"
          min={1}
          max={8}
          step={1}
          value={value}
          aria-label="Listings drafted at once"
          aria-valuetext={`${value} at once`}
          style={{ ["--sp-fill" as string]: `${((value - 1) / 7) * 100}%` }}
          onChange={(e) => setValue(Number(e.target.value))}
          onPointerUp={commit}
          onKeyUp={commit}
          onBlur={commit}
        />
        <div className="sp-slider__ticks" aria-hidden="true">
          {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => (
            <span key={n} className={n === value ? "is-on" : undefined}>
              {n}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- market

const toShares = (vals: number[]) => {
  const total = vals.reduce((a, b) => a + b, 0) || 1;
  const raw = vals.map((v) => Math.round((v / total) * 100));
  raw[raw.length - 1] += 100 - raw.reduce((a, b) => a + b, 0);
  return raw;
};

function Market({
  ref_,
  status,
  onSave,
}: {
  ref_: React.RefObject<HTMLElement>;
  status: "saved" | "saving";
  onSave: () => void;
}) {
  const fallback = toShares(startWeights.map((w) => w.fallback));
  const [shares, setShares] = useState(() => toShares(startWeights.map((w) => w.value)));
  const [active, setActive] = useState<number | null>(null);
  const bar = useRef<HTMLDivElement>(null);
  const changed = useRef(false);

  // Divider i sits between segment i and i+1, at the running total up to i.
  const edges = shares.slice(0, -1).map((_, i) => shares.slice(0, i + 1).reduce((a, b) => a + b, 0));

  const moveDivider = (i: number, pct: number) => {
    const lo = i === 0 ? 0 : edges[i - 1];
    const hi = i + 1 < edges.length ? edges[i + 1] : 100;
    const at = Math.round(Math.min(hi, Math.max(lo, pct)));
    if (at === edges[i]) return;
    setShares((s) => {
      const next = [...s];
      next[i] = at - lo;
      next[i + 1] = hi - at;
      return next;
    });
    changed.current = true;
  };

  const pctAt = (clientX: number) => {
    const r = bar.current!.getBoundingClientRect();
    return ((clientX - r.left) / r.width) * 100;
  };

  // Dividers on the same spot (a signal at 0%) form a stack: the first move
  // decides which one is dragged - left takes the leftmost, right the rightmost.
  const pending = useRef<{ stack: number[]; x: number } | null>(null);

  const onDown = (e: PointerEvent, i: number) => {
    e.preventDefault();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    const stack = edges.map((x, j) => (x === edges[i] ? j : -1)).filter((j) => j >= 0);
    if (stack.length > 1) pending.current = { stack, x: e.clientX };
    else setActive(i);
  };
  const onMove = (e: PointerEvent) => {
    const p = pending.current;
    if (p) {
      const dx = e.clientX - p.x;
      if (Math.abs(dx) < 2) return;
      pending.current = null;
      const pick = dx < 0 ? Math.min(...p.stack) : Math.max(...p.stack);
      setActive(pick);
      moveDivider(pick, pctAt(e.clientX));
      return;
    }
    if (active !== null) moveDivider(active, pctAt(e.clientX));
  };
  const onUp = () => {
    pending.current = null;
    setActive(null);
    if (changed.current) {
      changed.current = false;
      onSave();
    }
  };
  const onKey = (e: KeyboardEvent, i: number) => {
    const step = e.shiftKey ? 5 : 1;
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      moveDivider(i, edges[i] + (e.key === "ArrowLeft" ? -step : step));
      onUp();
    }
  };

  const reset = () => {
    setShares(fallback);
    onSave();
  };
  const isDefault = shares.every((s, i) => s === fallback[i]);

  return (
    <section className="b-panel" aria-labelledby="sp-market" ref={ref_}>
      <div className="b-panel__head">
        <div>
          <h2 className="b-panel__title" id="sp-market">Market SEO scoring</h2>
          <p className="b-panel__lede">
            How much each signal counts when ranking comparable Etsy listings. Drag the dividers to share out 100%; the
            arrow keys move a focused divider by 1 (Shift for 5).
          </p>
        </div>
        <SaveStatus state={status} />
      </div>

      <div className="sp-weights" ref={bar}>
        {shares.map((s, i) => (
          <span
            key={startWeights[i].key}
            className="sp-weights__seg"
            style={{ width: `${s}%`, background: SEG[i] }}
            title={`${startWeights[i].label}: ${s}%`}
          >
            {s >= 9 ? `${s}%` : ""}
          </span>
        ))}
        {edges.map((x, i) => (
          <span
            key={i}
            role="separator"
            tabIndex={0}
            aria-orientation="vertical"
            aria-label={`Between ${startWeights[i].label} and ${startWeights[i + 1].label}`}
            aria-valuenow={x}
            aria-valuemin={0}
            aria-valuemax={100}
            className={active === i ? "sp-weights__divider is-active" : "sp-weights__divider"}
            style={{ left: `${x}%`, zIndex: 10 + i }}
            onPointerDown={(e) => onDown(e, i)}
            onPointerMove={onMove}
            onPointerUp={onUp}
            onPointerCancel={onUp}
            onKeyDown={(e) => onKey(e, i)}
          >
            <span className="sp-weights__grip" />
          </span>
        ))}
      </div>

      <ul className="sp-legend">
        {startWeights.map((w, i) => (
          <li key={w.key} className={shares[i] === 0 ? "is-zero" : undefined}>
            <span className="b-share__key" style={{ background: shares[i] > 0 ? SEG[i] : "transparent", outline: shares[i] > 0 ? "none" : "1px solid var(--color-divider)" }} />
            <span className="sp-legend__text">
              <span className="b-weight__label">{w.label}</span>
              <span className="b-weight__pct">{w.hint}</span>
            </span>
            <span className="sp-legend__pct">{shares[i] === 0 ? "Not counted" : `${shares[i]}%`}</span>
          </li>
        ))}
      </ul>

      <div className="sp-market-foot">
        <span className="s-muted">A signal at 0% is not counted. Drag its divider out to bring it back.</span>
        <button type="button" className="btn btn-ghost" onClick={reset} disabled={isDefault}>
          <ArrowCounterClockwiseIcon size={15} /> Reset to defaults
        </button>
      </div>
    </section>
  );
}
