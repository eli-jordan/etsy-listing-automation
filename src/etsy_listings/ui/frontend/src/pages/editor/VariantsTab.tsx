import { useEffect, useMemo, useState } from "react";
import { listTemplates, templateThumbnailUrl } from "../../api/calibrator";
import { listGarmentProfiles } from "../../api/listings";
import type { GarmentProfileSummary, ListingDetail, TemplateSummary } from "../../types";

/**
 * Garment dropdown, sizes, colour list, and a preview of the colour under the
 * cursor (phase 5).
 *
 * No invented hex swatch: nothing in the domain model carries a colour's hex
 * value, so a row is name + light/dark badge. What answers "does this colour
 * suit the design?" is the *photo* -- which the workspace does have, one per
 * colour of a colour-matrix template, and which the preview stage shows.
 *
 * Two different states, deliberately distinguished, because conflating them
 * painted every enabled row in the selected-row highlight:
 *
 * * **enabled** -- the colour is in `colors:` and will be sold. The switch.
 * * **previewed** -- the colour on the stage right now. Exactly one, and
 *   `.color-row--selected` means *this*, not "enabled".
 *
 * A disabled colour is dimmed (`--off`) rather than hidden, so turning one
 * back on does not require remembering it existed.
 */

interface Props {
  detail: ListingDetail;
  onUpdate: (patch: Record<string, unknown>) => void;
}

/** The template whose photos stand in for this listing's colours: the first
 * `colour-matrix` one its own `media:` references. Not "any colour-matrix
 * template in the workspace" -- a preview should show a garment this listing
 * actually ships, and `media:` is where that is decided (PRD 31). */
function previewTemplate(detail: ListingDetail, templates: TemplateSummary[]): string | null {
  const byName = new Map(templates.map((t) => [t.name, t]));
  for (const entry of detail.media) {
    if (typeof entry === "string") continue;
    if (byName.get(entry.template)?.kind === "colour-matrix") return entry.template;
  }
  return null;
}

export function VariantsTab({ detail, onUpdate }: Props) {
  const [profiles, setProfiles] = useState<GarmentProfileSummary[]>([]);
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [status, setStatus] = useState("");
  const [previewColour, setPreviewColour] = useState<string | null>(null);

  useEffect(() => {
    listGarmentProfiles()
      .then(setProfiles)
      .catch(() => setStatus("failed to load garment profiles"));
    listTemplates()
      .then(setTemplates)
      .catch(() => setStatus("failed to load templates"));
  }, []);

  const profile = profiles.find((p) => p.name === detail.garment_profile);
  // Every colour the profile classifies, plus any the listing already enables
  // that the profile doesn't (so toggling one off never makes it vanish from
  // the list before the edit is saved).
  const colourNames = useMemo(
    () =>
      Array.from(
        new Set([...(profile ? Object.keys(profile.colors) : []), ...detail.colors]),
      ).sort(),
    [profile, detail.colors],
  );

  // Falls back rather than holding state the listing may have moved past: a
  // colour switched off, or renamed, should not leave the stage pointing at
  // something this listing no longer sells.
  const shown =
    previewColour !== null && colourNames.includes(previewColour)
      ? previewColour
      : (detail.colors[0] ?? colourNames[0] ?? null);

  const template = previewTemplate(detail, templates);

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
            const rowClass = [
              "color-row",
              colour === shown ? "color-row--selected" : "",
              enabled ? "" : "color-row--off",
            ]
              .filter(Boolean)
              .join(" ");
            return (
              <div key={colour} className={rowClass}>
                <button
                  type="button"
                  className="color-row__text"
                  aria-label={`Preview ${colour}`}
                  onClick={() => setPreviewColour(colour)}
                >
                  <span className="color-row__name">{colour}</span>
                  {classification && (
                    <span
                      className={classification === "dark" ? "tag tag-neutral" : "tag tag-accent"}
                    >
                      {classification}
                    </span>
                  )}
                </button>
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

      <div className="variants-preview">
        <span className="section-label">Preview</span>
        <div className="preview-stage preview-stage--compact">
          {template !== null && shown !== null ? (
            <>
              <span className="preview-stage__tag tag tag-neutral">{shown}</span>
              <img src={templateThumbnailUrl(template, shown)} alt={`${shown} on ${template}`} />
            </>
          ) : (
            <div className="image-placeholder">
              <span>Add a colour-matrix mockup on Listing Images to preview colours here.</span>
            </div>
          )}
        </div>
        <p className="variants-preview__hint">
          Click a colour to preview it — helps judge whether it suits the design.
        </p>
        <p role="status" className="app__status">
          {status}
        </p>
      </div>
    </div>
  );
}
