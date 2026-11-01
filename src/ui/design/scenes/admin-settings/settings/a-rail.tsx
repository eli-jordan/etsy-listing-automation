import { ArrowCounterClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowCounterClockwise";
import { ArrowClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowClockwise";
import { DotsSixVerticalIcon } from "@phosphor-icons/react/dist/csr/DotsSixVertical";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { Fragment } from "react";
import { batchConcurrency, providers, share, weights } from "../_fixtures";
import { PageHead, SaveStatus, SectionList, Select, StatusDot, Switch } from "../_parts";

export const meta = {
  title: "A · Ledger rows — Settings",
  viewport: "laptop",
  description: "Direction A: a plain text section rail and label-left, control-right rows; providers as a compact ordered table.",
};

export default function Frame() {
  return (
    <>
      <PageHead />
      <div className="adm-body">
        <SectionList active="settings" variant="plain" goto={(s) => `admin-settings/${s}/a-rail`} />
        <div>
          <section className="a-group" aria-labelledby="a-ai">
            <div className="a-group__head">
              <div>
                <h2 className="a-group__title" id="a-ai">AI providers</h2>
                <p className="a-group__lede">
                  Every AI run tries these in order and moves to the next one if a provider is unavailable or fails. Drag to
                  reorder. At least one stays on.
                </p>
              </div>
              <SaveStatus state="saved" text="Saved just now" />
            </div>
            <table className="a-providers">
              <thead>
                <tr>
                  <th aria-label="Reorder" />
                  <th aria-label="Position" />
                  <th>Provider</th>
                  <th>On</th>
                  <th style={{ width: 230 }}>Model</th>
                  <th style={{ width: 130 }}>Reasoning</th>
                </tr>
              </thead>
              <tbody>
                {providers.map((p, i) => (
                  <Fragment key={p.id}>
                    <tr className={p.enabled ? "" : "is-off"}>
                      <td style={{ width: 28 }}>
                        <button type="button" className="adm-handle" aria-label={`Move ${p.name}`}>
                          <DotsSixVerticalIcon size={18} />
                        </button>
                      </td>
                      <td className="a-providers__rank">{i + 1}</td>
                      <td>
                        <span className="a-providers__name">
                          {p.name}
                          <StatusDot status={p.status} text={p.statusText} />
                        </span>
                      </td>
                      <td>
                        <Switch on={p.enabled} label={`Use ${p.name}`} />
                      </td>
                      <td>
                        <Select value={p.model} options={p.models} label={`${p.name} model`} invalid={!!p.stale} />
                      </td>
                      <td>
                        <Select value={p.effort} options={p.efforts} label={`${p.name} reasoning`} />
                      </td>
                    </tr>
                    {p.stale && (
                      <tr className="a-stale">
                        <td colSpan={2} />
                        <td colSpan={4}>
                          <div className="adm-warn">
                            <WarningIcon size={15} />
                            <span>{p.stale}</span>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
            <div className="a-foot">
              <span className="adm-muted" style={{ fontSize: 12.5 }}>
                Model lists come from each CLI. Claude's is a fixed list. Changes apply from the next run.
              </span>
              <button type="button" className="btn btn-ghost">
                <ArrowClockwiseIcon size={15} /> Refresh lists
              </button>
            </div>
          </section>

          <section className="a-group" aria-labelledby="a-batch">
            <div className="a-group__head">
              <h2 className="a-group__title" id="a-batch">Batch AI</h2>
              <SaveStatus state="saved" />
            </div>
            <div className="a-row">
              <div>
                <div className="a-row__label">Listings drafted at once</div>
                <div className="a-row__hint">
                  Shared by every batch. Runs you start from the editor don't count. Lowering it lets running drafts finish.
                </div>
              </div>
              <div className="a-row__control">
                <input className="adm-number" type="number" min={1} max={8} defaultValue={batchConcurrency} aria-label="Listings drafted at once" />
                <span className="adm-muted" style={{ fontSize: 13 }}>of up to 8</span>
              </div>
            </div>
          </section>

          <section className="a-group" aria-labelledby="a-market">
            <div className="a-group__head">
              <div>
                <h2 className="a-group__title" id="a-market">Market SEO scoring</h2>
                <p className="a-group__lede">
                  How much each signal counts when ranking comparable Etsy listings. Only the proportions matter.
                </p>
              </div>
              <SaveStatus state="saving" />
            </div>
            {weights.map((w) => (
              <div className="a-weight" key={w.key}>
                <div>
                  <div className="a-row__label">{w.label}</div>
                  <div className="a-row__hint">{w.hint}</div>
                </div>
                <input className="adm-number" type="number" min={0} defaultValue={w.value} aria-label={w.label} />
                <div className="a-weight__bar">
                  <span className="a-weight__track">
                    <span className="a-weight__fill" style={{ display: "block", width: `${share(w.value)}%` }} />
                  </span>
                  <span style={{ width: 32, textAlign: "right" }}>{share(w.value)}%</span>
                </div>
              </div>
            ))}
            <div className="a-foot">
              <span className="adm-muted" style={{ fontSize: 12.5 }}>Two weights differ from the defaults.</span>
              <button type="button" className="btn btn-ghost">
                <ArrowCounterClockwiseIcon size={15} /> Reset to defaults
              </button>
            </div>
          </section>
        </div>
      </div>
    </>
  );
}
