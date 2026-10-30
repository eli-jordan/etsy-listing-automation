import { ArrowCounterClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowCounterClockwise";
import { DotsSixVerticalIcon } from "@phosphor-icons/react/dist/csr/DotsSixVertical";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { providers, share, weights } from "../_fixtures";
import { PageHead, SaveStatus, SectionList, Select, StatusDot, Switch } from "../_parts";

export const meta = {
  title: "B · Panels — Settings",
  viewport: "laptop",
  description:
    "Direction B: described section list, one surface panel per group; providers drawn as a numbered fallback chain; concurrency stepper shows its out-of-range error.",
};

const SEG = [
  "var(--color-accent-600)",
  "var(--color-accent-400)",
  "var(--color-accent-2-600)",
  "var(--color-accent-2-400)",
  "var(--color-neutral-600)",
  "var(--color-neutral-400)",
];

export default function Frame() {
  return (
    <>
      <PageHead />
      <div className="adm-body">
        <SectionList active="settings" variant="described" goto={(s) => `admin-settings/${s}/b-cards`} />
        <div>
          <section className="b-panel" aria-labelledby="b-ai">
            <div className="b-panel__head">
              <div>
                <h2 className="b-panel__title" id="b-ai">AI providers</h2>
                <p className="b-panel__lede">
                  Each run starts at the top and falls through to the next provider if one is unavailable or fails. Drag a
                  step to change the order.
                </p>
              </div>
              <SaveStatus state="saved" text="Saved just now" />
            </div>
            <ol className="b-chain">
              {providers.map((p, i) => (
                <li key={p.id} className={p.enabled ? "b-step" : "b-step is-off"}>
                  <span className="b-step__num" aria-hidden="true">
                    {p.enabled ? i + 1 : "–"}
                  </span>
                  <div className="b-step__body">
                    <div className="b-step__top" style={p.enabled ? undefined : { marginBottom: 0 }}>
                      <button type="button" className="adm-handle" aria-label={`Move ${p.name}`}>
                        <DotsSixVerticalIcon size={18} />
                      </button>
                      <span className="b-step__name">{p.name}</span>
                      <StatusDot status={p.status} text={p.statusText} />
                      <span className="b-step__spacer" />
                      {!p.enabled && <span className="b-step__off-note">Off — runs skip it</span>}
                      <Switch on={p.enabled} label={`Use ${p.name}`} />
                    </div>
                    {p.enabled && (
                      <div className="b-step__fields">
                        <div>
                          <label>Model · {p.source.toLowerCase()}</label>
                          <Select value={p.model} options={p.models} label={`${p.name} model`} />
                        </div>
                        <div>
                          <label>Reasoning</label>
                          <Select value={p.effort} options={p.efforts} label={`${p.name} reasoning`} />
                        </div>
                      </div>
                    )}
                    {!p.enabled && p.stale && (
                      <div className="adm-warn" style={{ marginTop: "var(--space-3)" }}>
                        <WarningIcon size={15} />
                        <span>{p.stale}</span>
                      </div>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </section>

          <section className="b-panel" aria-labelledby="b-batch">
            <div className="b-panel__head">
              <div>
                <h2 className="b-panel__title" id="b-batch">Batch AI</h2>
                <p className="b-panel__lede">
                  How many listings in a batch are drafted at the same time, across all batches. Editor runs don't count.
                </p>
              </div>
              <SaveStatus state="error" text="Not saved" />
            </div>
            <div className="b-conc">
              <div className="b-stepper b-stepper--error">
                <button type="button" aria-label="Fewer">−</button>
                <input defaultValue={9} aria-label="Listings drafted at once" aria-invalid="true" />
                <button type="button" aria-label="More" disabled>
                  +
                </button>
              </div>
              <span className="adm-error-text">Choose 1 to 8. The saved value, 2, is still in use.</span>
            </div>
          </section>

          <section className="b-panel" aria-labelledby="b-market">
            <div className="b-panel__head">
              <div>
                <h2 className="b-panel__title" id="b-market">Market SEO scoring</h2>
                <p className="b-panel__lede">How much each signal counts when ranking comparable Etsy listings.</p>
              </div>
              <button type="button" className="btn btn-ghost">
                <ArrowCounterClockwiseIcon size={15} /> Reset to defaults
              </button>
            </div>
            <div className="b-share" role="img" aria-label="Share of the total score per signal">
              {weights
                .filter((w) => w.value > 0)
                .map((w, i) => (
                  <span key={w.key} className="b-share__seg" style={{ width: `${share(w.value)}%`, background: SEG[i] }}>
                    {share(w.value) >= 9 ? `${share(w.value)}%` : ""}
                  </span>
                ))}
            </div>
            <div className="b-share__legend">
              {weights.map((w, i) => (
                <span key={w.key}>
                  <span className="b-share__key" style={{ background: w.value > 0 ? SEG[i] : "transparent", outline: w.value > 0 ? "none" : "1px solid var(--color-divider)" }} />
                  {w.label}
                </span>
              ))}
            </div>
            <div className="b-weights">
              {weights.map((w) => (
                <div className="b-weight" key={w.key}>
                  <span>
                    <span className="b-weight__label">{w.label}</span>
                    <br />
                    <span className="b-weight__pct">{w.value === 0 ? "Not counted" : `${share(w.value)}% of the score`}</span>
                  </span>
                  <input className="adm-number" type="number" min={0} defaultValue={w.value} aria-label={w.label} />
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>
    </>
  );
}
