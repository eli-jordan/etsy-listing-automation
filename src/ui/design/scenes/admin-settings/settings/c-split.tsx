import { ArrowCounterClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowCounterClockwise";
import { DotsSixVerticalIcon } from "@phosphor-icons/react/dist/csr/DotsSixVertical";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { batchConcurrency, providers, share, weights } from "../_fixtures";
import { PageHead, SaveStatus, SectionList, Select, StatusDot, Switch } from "../_parts";

export const meta = {
  title: "C · Form + explanation — Settings",
  viewport: "laptop",
  description:
    "Direction C: compact icon list, a form column, and a right column that says in plain words what the next AI run and market scoring will do.",
};

const labelFor = (id: string, opts: { id: string; label: string }[]) => opts.find((o) => o.id === id)?.label ?? id;

export default function Frame() {
  return (
    <>
      <PageHead />
      <div className="c-conflict" role="alert">
        <WarningIcon size={18} />
        <span className="c-conflict__text">
          <strong>settings.yaml changed outside the app.</strong> Your last change to Market SEO wasn't saved, so nothing
          was overwritten.
        </span>
        <button type="button" className="btn btn-secondary">Reload settings</button>
      </div>
      <div className="c-body">
        <SectionList active="settings" variant="compact" goto={(s) => `admin-settings/${s}/c-split`} />

        <div className="c-form">
          <section aria-labelledby="c-ai">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <h2 className="c-block__title" id="c-ai">AI providers</h2>
              <SaveStatus state="saved" />
            </div>
            <p className="c-block__lede">Tried in this order. Drag to reorder; switch off any you don't want used.</p>
            {providers.map((p) => (
              <div key={p.id} className={`c-prov${p.enabled ? "" : " is-off"}`}>
                <button type="button" className="adm-handle" aria-label={`Move ${p.name}`}>
                  <DotsSixVerticalIcon size={18} />
                </button>
                <span className="c-prov__name">
                  {p.name}
                  <StatusDot status={p.status} text={p.statusText} />
                </span>
                <span className="c-prov__dim c-prov__model">
                  <Select value={p.model} options={p.models} label={`${p.name} model`} invalid={!!p.stale} />
                </span>
                <span className="c-prov__dim c-prov__effort">
                  <Select value={p.effort} options={p.efforts} label={`${p.name} reasoning`} />
                </span>
                <Switch on={p.enabled} label={`Use ${p.name}`} />
                {p.stale && (
                  <div className="c-prov__stale adm-warn">
                    <WarningIcon size={15} />
                    <span>{p.stale}</span>
                  </div>
                )}
              </div>
            ))}
          </section>

          <section aria-labelledby="c-batch">
            <h2 className="c-block__title" id="c-batch">Batch AI</h2>
            <p className="c-block__lede">Shared by every batch. Editor runs don't count against it.</p>
            <div className="c-field" style={{ maxWidth: 260 }}>
              <label>Listings drafted at once</label>
              <Select value={String(batchConcurrency)} options={["1", "2", "3", "4", "5", "6", "7", "8"]} label="Listings drafted at once" />
              <div className="c-field__hint">Lowering it lets drafts already running finish.</div>
            </div>
          </section>

          <section aria-labelledby="c-market">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <h2 className="c-block__title" id="c-market">Market SEO scoring</h2>
              <SaveStatus state="error" text="Not saved — reload first" />
            </div>
            <p className="c-block__lede">Weights are relative: only the proportions matter.</p>
            <div className="c-weights">
              {weights.map((w) => (
                <div className="c-weight" key={w.key}>
                  <span className="c-weight__label">
                    {w.label}
                    <span className="c-weight__hint">{w.hint}</span>
                  </span>
                  <input className="adm-number" type="number" min={0} defaultValue={w.value} aria-label={w.label} />
                </div>
              ))}
            </div>
            <button type="button" className="btn btn-ghost" style={{ marginTop: "var(--space-3)" }}>
              <ArrowCounterClockwiseIcon size={15} /> Reset to defaults
            </button>
          </section>
        </div>

        <aside className="c-aside" aria-label="What these settings do">
          <div className="c-explain">
            <h3 className="c-explain__title">The next AI run</h3>
            <ol className="c-run">
              {providers.map((p, i) => (
                <li key={p.id} className={p.enabled ? "" : "is-off"}>
                  <span className="c-run__n">{i + 1}</span>
                  <span>
                    {p.enabled ? (
                      <>
                        <strong>{p.name}</strong> with {labelFor(p.model, p.models)}, {p.effort} reasoning
                      </>
                    ) : (
                      <>{p.name} is off</>
                    )}
                  </span>
                </li>
              ))}
            </ol>
            <p className="adm-muted">
              Batches draft {batchConcurrency} listings at a time using the same order.
            </p>
          </div>
          <div className="c-explain">
            <h3 className="c-explain__title">Share of the market score</h3>
            <div className="c-bars">
              {weights.map((w) => (
                <div className="c-bar" key={w.key}>
                  <span>{w.label}</span>
                  <span className="c-bar__track">
                    <span className="c-bar__fill" style={{ display: "block", width: `${share(w.value)}%` }} />
                  </span>
                  <span className="c-bar__pct">{share(w.value)}%</span>
                </div>
              ))}
            </div>
          </div>
        </aside>
      </div>
    </>
  );
}
