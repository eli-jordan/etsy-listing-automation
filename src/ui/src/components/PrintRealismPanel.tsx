import type { DisplaceConfig, ShadeBlend, ShadeConfig } from "../types";

/**
 * The two tunable passes, named for what they do to a photograph. The raw pass
 * names stay under *Advanced*: template.yaml, the goldens and every error use them.
 */

const DISPLACE_DEFAULT: DisplaceConfig = { enabled: false, strength: 0 };
const SHADE_DEFAULT: ShadeConfig = { enabled: true, opacity: 0.6, blend: "soft-light" };

/** `Natural` is `soft-light`, the config default: multiply crushes prints on dark garments. */
const SHADE_PRESETS: { label: string; blend: ShadeBlend }[] = [
  { label: "Natural", blend: "soft-light" },
  { label: "Rich", blend: "multiply" },
  { label: "Airy", blend: "grey-pivot" },
];

function percent(fraction: number): number {
  return Math.round(fraction * 100);
}

interface PassProps {
  id: string;
  title: string;
  sliderLabel: string;
  low: string;
  high: string;
  enabled: boolean;
  value: number;
  onToggle: (enabled: boolean) => void;
  onValue: (fraction: number) => void;
  children?: React.ReactNode;
}

function Pass({
  id,
  title,
  sliderLabel,
  low,
  high,
  enabled,
  value,
  onToggle,
  onValue,
  children,
}: PassProps) {
  return (
    <div className="realism__pass">
      <div className="realism__row">
        <label className="realism__title" htmlFor={id}>
          {title}
        </label>
        <input
          id={id}
          type="checkbox"
          checked={enabled}
          onChange={(e) => onToggle(e.target.checked)}
        />
      </div>
      <div className="realism__row">
        <input
          aria-label={sliderLabel}
          type="range"
          min={0}
          max={100}
          step={1}
          value={percent(value)}
          disabled={!enabled}
          onChange={(e) => onValue(Number(e.target.value) / 100)}
        />
        <span className="realism__value">{`${percent(value)}%`}</span>
      </div>
      <p className="realism__scale">
        {low} <span aria-hidden="true">———</span> {high}
      </p>
      {children}
    </div>
  );
}

interface Props {
  displace: DisplaceConfig;
  shade: ShadeConfig;
  onDisplaceChange: (next: DisplaceConfig) => void;
  onShadeChange: (next: ShadeConfig) => void;
}

export function PrintRealismPanel({ displace, shade, onDisplaceChange, onShadeChange }: Props) {
  return (
    <section className="realism" aria-label="Print realism">
      <div className="realism__head">
        <h3 className="realism__heading">Print realism</h3>
        <button
          type="button"
          className="btn btn-ghost"
          aria-label="Reset print realism"
          onClick={() => {
            onDisplaceChange(DISPLACE_DEFAULT);
            onShadeChange(SHADE_DEFAULT);
          }}
        >
          Reset
        </button>
      </div>

      <Pass
        id="realism-wrinkles"
        title="Follow fabric wrinkles"
        sliderLabel="Wrinkle strength"
        low="flat"
        high="heavy creasing"
        enabled={displace.enabled}
        value={displace.strength}
        onToggle={(enabled) => onDisplaceChange({ ...displace, enabled })}
        onValue={(strength) => onDisplaceChange({ ...displace, strength })}
      />

      <hr className="realism__divider" />

      <Pass
        id="realism-shading"
        title="Pick up garment shading"
        sliderLabel="Shading strength"
        low="none"
        high="deep shadows"
        enabled={shade.enabled}
        value={shade.opacity}
        onToggle={(enabled) => onShadeChange({ ...shade, enabled })}
        onValue={(opacity) => onShadeChange({ ...shade, opacity })}
      >
        <div className="realism__presets">
          {SHADE_PRESETS.map(({ label, blend }) => (
            <button
              key={blend}
              type="button"
              className={`tag template-rail__pill${
                shade.blend === blend ? " template-rail__pill--on" : ""
              }`}
              aria-pressed={shade.blend === blend}
              onClick={() => onShadeChange({ ...shade, blend })}
            >
              {label}
            </button>
          ))}
        </div>
        <p className="realism__scale">shading style</p>
      </Pass>

      <details className="realism__advanced">
        <summary>Advanced (displace / blend values)</summary>
        <dl className="realism__raw">
          <dt>displace.strength</dt>
          <dd>{displace.strength.toFixed(2)}</dd>
          <dt>shade.opacity</dt>
          <dd>{shade.opacity.toFixed(2)}</dd>
          <dt>shade.blend</dt>
          <dd>{shade.blend}</dd>
        </dl>
      </details>
    </section>
  );
}
