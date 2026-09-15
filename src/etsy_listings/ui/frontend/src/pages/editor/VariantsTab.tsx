import { useEffect, useState } from "react";
import { listGarmentProfiles } from "../../api/listings";
import type { GarmentProfileSummary, ListingDetail } from "../../types";

/** Garment dropdown, sizes, colour list (phase 5). No invented hex swatch --
 * nothing in the domain model carries a colour's hex value, so a colour row
 * is name + light/dark badge, per the mockup-vs-domain-model decisions in
 * phase-5-listings-ui.md. */

interface Props {
  detail: ListingDetail;
  onUpdate: (patch: Record<string, unknown>) => void;
}

export function VariantsTab({ detail, onUpdate }: Props) {
  const [profiles, setProfiles] = useState<GarmentProfileSummary[]>([]);
  const [status, setStatus] = useState("");

  useEffect(() => {
    listGarmentProfiles()
      .then(setProfiles)
      .catch(() => setStatus("failed to load garment profiles"));
  }, []);

  const profile = profiles.find((p) => p.name === detail.garment_profile);
  // Every colour the profile classifies, plus any the listing already enables
  // that the profile doesn't (so toggling one off never makes it vanish from
  // the list before the edit is saved).
  const colourNames = Array.from(
    new Set([...(profile ? Object.keys(profile.colors) : []), ...detail.colors]),
  ).sort();

  function toggleColour(colour: string, enabled: boolean) {
    const next = enabled ? [...detail.colors, colour] : detail.colors.filter((c) => c !== colour);
    onUpdate({ colors: next });
  }

  return (
    <div className="layout--variants">
      <fieldset>
        <legend>Variants</legend>

        <div className="field">
          <label htmlFor="variants-garment">Garment profile</label>
          <select
            id="variants-garment"
            value={detail.garment_profile}
            onChange={(event) => onUpdate({ garment_profile: event.target.value })}
          >
            {!profile && <option value={detail.garment_profile}>{detail.garment_profile}</option>}
            {profiles.map((p) => (
              <option key={p.name} value={p.name}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        {profile && (
          <div className="field">
            <label>Sizes</label>
            <div className="garment-card__sizes">
              {profile.sizes.map((size) => (
                <span key={size} className="size-pill">
                  {size}
                </span>
              ))}
            </div>
          </div>
        )}

        <div className="field">
          <div className="colors-panel__head">
            <label style={{ margin: 0 }}>Colours</label>
            <span className="colors-panel__count">
              {detail.colors.length} of {colourNames.length} included
            </span>
          </div>
          {colourNames.map((colour) => {
            const enabled = detail.colors.includes(colour);
            const classification = profile?.colors[colour];
            return (
              <div key={colour} className={enabled ? "color-row color-row--selected" : "color-row"}>
                <div className="color-row__text">
                  <span className="color-row__name">{colour}</span>
                  {classification && (
                    <span
                      className={classification === "dark" ? "tag tag-neutral" : "tag tag-accent"}
                    >
                      {classification}
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={enabled}
                  aria-label={colour}
                  className={enabled ? "switch switch--on" : "switch"}
                  onClick={() => toggleColour(colour, !enabled)}
                >
                  <span className="switch__knob" />
                </button>
              </div>
            );
          })}
        </div>
      </fieldset>

      <p role="status" className="app__status">
        {status}
      </p>
    </div>
  );
}
