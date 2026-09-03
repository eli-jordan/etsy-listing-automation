import type { DisplaceConfig, ShadeBlend, ShadeConfig } from "../types";

/**
 * The two tunable render passes, as controls. Split out of App so the page
 * body reads as layout rather than a wall of nested onChange handlers -- and
 * so each pass's controls sit next to the config type they edit.
 */

const SHADE_BLENDS: ShadeBlend[] = ["soft-light", "multiply", "grey-pivot"];

interface DisplaceProps {
  value: DisplaceConfig;
  onChange: (next: DisplaceConfig) => void;
}

export function DisplaceControls({ value, onChange }: DisplaceProps) {
  return (
    <fieldset>
      <legend>Displace</legend>
      <label>
        <input
          type="checkbox"
          checked={value.enabled}
          onChange={(e) => onChange({ ...value, enabled: e.target.checked })}
        />
        enabled
      </label>
      <label>
        strength
        <input
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={value.strength}
          onChange={(e) => onChange({ ...value, strength: Number(e.target.value) })}
        />
      </label>
    </fieldset>
  );
}

interface ShadeProps {
  value: ShadeConfig;
  onChange: (next: ShadeConfig) => void;
}

export function ShadeControls({ value, onChange }: ShadeProps) {
  return (
    <fieldset>
      <legend>Shade</legend>
      <label>
        <input
          type="checkbox"
          checked={value.enabled}
          onChange={(e) => onChange({ ...value, enabled: e.target.checked })}
        />
        enabled
      </label>
      <label>
        opacity
        <input
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={value.opacity}
          onChange={(e) => onChange({ ...value, opacity: Number(e.target.value) })}
        />
      </label>
      <label>
        blend
        <select
          value={value.blend}
          onChange={(e) => onChange({ ...value, blend: e.target.value as ShadeBlend })}
        >
          {SHADE_BLENDS.map((blend) => (
            <option key={blend} value={blend}>
              {blend}
            </option>
          ))}
        </select>
      </label>
    </fieldset>
  );
}
