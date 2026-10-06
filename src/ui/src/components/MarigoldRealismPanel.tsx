import { MARIGOLD_DEFAULTS } from "../editors/marigoldDefaults";
import { useState } from "react";
import { InfoIcon } from "@phosphor-icons/react/dist/csr/Info";
import type { Renderer } from "../types";
import "./marigold.css";

type Appearance = Extract<Renderer, { type: "marigold" }>["config"]["appearance"];
const fields = {
  lighting_source: {
    label: "Lighting source",
    help: "Prepared garment lighting uses the lighting estimated during preparation. Photo-based lighting uses brightness from the original photo, which can also pick up the shirt's colour and texture.",
  },
  lighting_strength: {
    label: "Light & shadow strength",
    help: "At 0% the design keeps its original brightness; at 100% it follows the cloth's shading fully.",
    low: "Original artwork",
    high: "Full cloth shading",
  },
  fabric_texture: {
    label: "Fabric texture",
    help: "Adds fine cloth texture and small wrinkles to the print. This does not change placement or the larger folds.",
    low: "Smooth",
    high: "More texture",
  },
  print_shine: {
    label: "Print shine",
    help: "Adds bright reflections from the garment to the print. Higher values can wash out design detail. Leave at 0% for a matte print.",
    low: "Matte",
    high: "Shiny",
  },
};
export function MarigoldRealismPanel({
  value,
  onChange,
}: {
  value: Appearance;
  onChange: (next: Appearance) => void;
}) {
  const [help, setHelp] = useState<keyof Appearance | null>(null);
  return (
    <section
      className="realism"
      onKeyDown={(e) => {
        if (e.key === "Escape") setHelp(null);
      }}
    >
      <div className="realism__head">
        <h3>Print realism</h3>
        <button
          className="btn-ghost"
          onClick={() => onChange({ ...MARIGOLD_DEFAULTS.config.appearance })}
        >
          Reset
        </button>
      </div>
      {(Object.keys(fields) as (keyof Appearance)[]).map((key) => (
        <div className="realism__pass" key={key}>
          <div className="mg-field-title">
            <label htmlFor={`realism-${key}`}>{fields[key].label}</label>
            <button
              type="button"
              className="mg-info"
              aria-label={`About ${fields[key].label}`}
              aria-expanded={help === key}
              aria-controls={`help-${key}`}
              onClick={() => setHelp(help === key ? null : key)}
            >
              <InfoIcon />
            </button>
          </div>
          {key === "lighting_source" ? (
            <select
              id={`realism-${key}`}
              value={value[key]}
              onChange={(e) =>
                onChange({
                  ...value,
                  lighting_source: e.target.value as Appearance["lighting_source"],
                })
              }
            >
              <option value="estimated">Prepared garment lighting</option>
              <option value="photo">Photo-based lighting</option>
            </select>
          ) : (
            <>
              <div className="realism__row">
                <input
                  id={`realism-${key}`}
                  type="range"
                  min={0}
                  max={100}
                  value={Math.round(value[key] * 100)}
                  onChange={(e) => onChange({ ...value, [key]: Number(e.target.value) / 100 })}
                />
                <span className="realism__value">{Math.round(value[key] * 100)}%</span>
              </div>
              <p className="realism__scale">
                {fields[key].low} <span>{fields[key].high}</span>
              </p>
            </>
          )}
          {help === key && (
            <p className="mg-info-text" id={`help-${key}`}>
              {fields[key].help}
            </p>
          )}
        </div>
      ))}
    </section>
  );
}
