import type { DisplaceConfig, ShadeBlend, ShadeConfig } from "../types";

/**
 * The two tunable render passes, named after what they do to a photograph.
 *
 * `displace` and `shade` are accurate names for what the code does and useless
 * names for deciding whether a mockup looks right -- the question in front of
 * the user is "does the print follow the creases?", not "what is the
 * displacement strength?". Wireframe 2a renames them, and turns the blend mode
 * into three named looks.
 *
 * The raw values stay reachable under *Advanced*: `template.yaml`, the render
 * goldens and every error message speak in pass names, so renaming them here
 * must not make them unfindable.
 */

const DISPLACE_DEFAULT: DisplaceConfig = { enabled: false, strength: 0 };
const SHADE_DEFAULT: ShadeConfig = { enabled: true, opacity: 0.6, blend: "soft-light" };

/** Named for the result, not the maths. `Natural` is `soft-light`, which is
 * also the config default -- multiply crushes prints on dark garments, so the
 * safe choice and the obvious-sounding one are deliberately the same. */
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
        {/* Reads "Reset" but announces what it resets: the header has its own
            Reset that throws away every unsaved edit, and two controls with
            the same name doing different things is a trap for anyone not
            looking directly at them. */}
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
