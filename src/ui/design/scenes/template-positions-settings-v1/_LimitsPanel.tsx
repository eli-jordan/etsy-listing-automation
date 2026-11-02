import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { useState } from "react";
import "../../../src/pages/admin/admin.css";
import "../../../src/pages/admin/settings.css";
import { PageHead, SaveStatus, SectionList } from "../admin-settings/_parts";
import "./_limits.css";

export interface LimitValues {
  smallest: number;
  largest: number;
  offset: number;
  tilt: number;
}
export const saved: LimitValues = { smallest: 80, largest: 110, offset: 10, tilt: 15 };

interface SliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit: string;
  hint: string;
  onChange: (v: number) => void;
}

function Slider({ label, value, min, max, step, unit, hint, onChange }: SliderProps) {
  return (
    <div className="tl-row">
      <div className="tl-row__label">
        <span>{label}</span>
        <span className="tl-row__hint">{hint}</span>
      </div>
      <div className="sp-slider">
        <span className="sp-slider__value" aria-hidden="true">
          <strong>
            {value}
            {unit}
          </strong>
        </span>
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          aria-label={label}
          style={{ ["--sp-fill" as string]: `${((value - min) / (max - min)) * 100}%` }}
          onChange={(e) => onChange(Number(e.target.value))}
        />
      </div>
    </div>
  );
}

/**
 * Settings > Template positions. The limits every listing's position is
 * checked against. Marigold padding follows them, so any change re-prepares
 * those templates -- the panel says so before the save, not after.
 */
export function LimitsPanel({ initial, onReview }: { initial: LimitValues; onReview?: string }) {
  const [v, setV] = useState(initial);
  const changed = JSON.stringify(v) !== JSON.stringify(saved);
  const set = (k: keyof LimitValues) => (n: number) => setV((cur) => ({ ...cur, [k]: n }));

  return (
    <div className="adm-page">
      <PageHead />
      <div className="adm-body">
        <SectionList active="settings" variant="described" goto={() => "template-positions-settings-v1/01-limits"} />
        <div className="settings-panels">
          <section className="b-panel" aria-labelledby="tl-title">
            <div className="b-panel__head">
              <div>
                <h2 className="b-panel__title" id="tl-title">
                  Template positions
                </h2>
                <p className="b-panel__lede">
                  How far a listing may move the design away from a mockup template's own box. Mockups only:
                  Printify always prints centred at full size, so keep these small enough that the photo stays
                  honest.
                </p>
              </div>
              {!changed && <SaveStatus state="saved" text="Saved" />}
            </div>

            <Slider label="Smallest" value={v.smallest} min={50} max={100} step={5} unit="%" hint="of the template's box" onChange={set("smallest")} />
            <Slider label="Largest" value={v.largest} min={100} max={150} step={5} unit="%" hint="of the template's box" onChange={set("largest")} />
            <Slider label="Move" value={v.offset} min={0} max={25} step={1} unit="%" hint="of box width or height, each way" onChange={set("offset")} />
            <Slider label="Tilt" value={v.tilt} min={0} max={30} step={1} unit="°" hint="each way" onChange={set("tilt")} />

            <div className={changed ? "adm-warn tl-cost tl-cost--live" : "tl-cost"} role={changed ? "alert" : undefined}>
              <WarningIcon size={18} />
              <span>
                <strong>Changing these re-prepares 3 Marigold templates.</strong> Their maps are fitted to cover
                these limits. It runs in the background and takes about 20 minutes; their listings can't preview
                or deploy until it finishes. Narrowing also blocks any listing whose saved position falls outside.
              </span>
            </div>

            <div className="tl-foot">
              <button type="button" className="btn btn-ghost" disabled={!changed} onClick={() => setV(saved)}>
                Discard
              </button>
              <button type="button" className="btn btn-primary" disabled={!changed} data-goto={onReview}>
                Review and save…
              </button>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
