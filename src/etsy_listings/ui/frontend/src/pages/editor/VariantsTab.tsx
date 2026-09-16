import { useEffect, useMemo, useState } from "react";
import {
  getTemplateSwatch,
  listTemplates,
  templateDesignPreviewUrl,
  templateThumbnailUrl,
} from "../../api/calibrator";
import { listGarmentProfiles } from "../../api/listings";
import type { GarmentProfileSummary, ListingDetail, TemplateSummary } from "../../types";
import { mediaLostBy, selectColours, selectGarmentProfile } from "./colourSelection";
import { singleDesignName } from "./designName";

/**
 * Garment dropdown, sizes, colour list, and a preview of the colour under the
 * cursor (phase 5).
 *
 * A swatch dot next to each name is the listing's *real* garment colour, not
 * an invented hex value -- sampled off the preview template's own scene
 * photo (`render/swatch.py`'s `sample_swatch`, via `GET .../swatch`). It
 * answers "roughly what colour is this" for scanning the whole list; "does
 * this colour suit the design" is still the big preview stage beside it, which
 * overlays the listing's real artwork (`GET .../design-preview`) rather than
 * showing a bare photo -- and is rendered large, because that judgement is
 * about the ink on the cloth and a postage stamp cannot carry it.
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
 *
 * Every change to which colours are sold goes through `selectColours`, never
 * through a bare `{ colors }` patch -- see that module for the three fields
 * keyed by colour that have to move with it.
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
  const [swatches, setSwatches] = useState<Record<string, string>>({});
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
  const design = singleDesignName(detail.design);

  // One request per colour, fired once the preview template and colour list
  // are known -- not per row-render, so scrolling or re-toggling a switch
  // never refetches a dot this effect has already resolved. Routed through
  // `Promise.all` even for "no template" so `setSwatches` is always called
  // from a `.then()`, never synchronously in the effect body.
  useEffect(() => {
    let current = true;
    const fetches =
      template === null
        ? []
        : colourNames.map((colour) =>
            getTemplateSwatch(template, colour)
              .then((hex) => [colour, hex] as const)
              .catch(() => null),
          );
    Promise.all(fetches).then((results) => {
      if (!current) return;
      setSwatches(Object.fromEntries(results.filter((r) => r !== null)));
    });
    return () => {
      current = false;
    };
  }, [template, colourNames]);

  /** The one write path for `colors:`. Reports what else the edit took with
   * it, since a bulk switch can drop a reel somebody spent a while building
   * and the reel is on a different tab. */
  function setColours(next: string[]) {
    const lost = mediaLostBy(detail, next);
    onUpdate(selectColours(detail, next));
    setStatus(
      lost === 0
        ? ""
        : `Removed ${lost} listing ${lost === 1 ? "image" : "images"} for colours no longer sold.`,
    );
  }

  function toggleColour(colour: string, enabled: boolean) {
    setColours(enabled ? [...detail.colors, colour] : detail.colors.filter((c) => c !== colour));
  }

  /** Every colour the newly chosen profile classifies, replacing whatever
   * was selected -- a new listing has none yet, and a switch between
   * garments would otherwise keep colours the new one does not sell. */
  function pickProfile(name: string) {
    const chosen = profiles.find((p) => p.name === name);
    const colours = chosen === undefined ? [] : Object.keys(chosen.colors).sort();
    const lost = mediaLostBy(detail, colours);
    onUpdate(selectGarmentProfile(detail, name, colours));
    setStatus(
      lost === 0
        ? ""
        : `Removed ${lost} listing ${lost === 1 ? "image" : "images"} for colours no longer sold.`,
    );
  }

  /** Every colour the garment profile classifies as ``shade``, and nothing
   * else -- the two bulk buttons are exact opposites, so "Dark" turning the
   * light ones *off* is the half that makes them worth having. Driven by the
   * profile, so a colour it does not classify is left out of both. */
  function onlyShade(shade: "dark" | "light") {
    if (!profile) return;
    setColours(colourNames.filter((colour) => profile.colors[colour] === shade));
  }

  // Offered only when there is something for them to act on: a garment
  // profile that classifies no colours (`colors: {}`) would give two buttons
  // that clear the list and call it a shade.
  const hasShades = profile !== undefined && Object.keys(profile.colors).length > 0;

  return (
    <div className="layout--variants">
      <fieldset>
        <legend>Variants</legend>

        <div className="field">
          <label htmlFor="variants-garment">Garment profile</label>
          <select
            id="variants-garment"
            value={detail.garment_profile}
            onChange={(event) => pickProfile(event.target.value)}
          >
            {/* A new listing starts with none chosen, so the unselected case
                needs words rather than the blank, unlabelled option an empty
                value would otherwise render. */}
            {!profile && (
              <option value={detail.garment_profile}>
                {detail.garment_profile || "Select a garment profile…"}
              </option>
            )}
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

          {/* Above the swatches, because they act on all of them: a design
              drawn for dark garments sells on the dark half of the profile
              and nothing else, and setting that one switch at a time is the
              most tedious thing this tab asks for. */}
          {hasShades && (
            <div className="shade-picker">
              <button type="button" className="btn-like btn-sm" onClick={() => onlyShade("dark")}>
                Dark
              </button>
              <button type="button" className="btn-like btn-sm" onClick={() => onlyShade("light")}>
                Light
              </button>
              <span className="shade-picker__hint">only these shades</span>
            </div>
          )}

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
                  {swatches[colour] && (
                    <span
                      className="color-row__swatch"
                      style={{ background: swatches[colour] }}
                      aria-hidden="true"
                    />
                  )}
                  <span className="color-row__name">{colour}</span>
                </button>
                {/* Beside the switch, not beside the name: the shade is what
                    the two bulk buttons above act on, so it reads as a
                    property of the decision rather than of the label. */}
                {classification && (
                  <span
                    className={classification === "dark" ? "tag tag-neutral" : "tag tag-accent"}
                  >
                    {classification}
                  </span>
                )}
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
        <div className="preview-stage preview-stage--large">
          {template !== null && shown !== null ? (
            <>
              <span className="preview-stage__tag tag tag-neutral">{shown}</span>
              <img
                src={
                  design !== null
                    ? templateDesignPreviewUrl(template, design, shown)
                    : templateThumbnailUrl(template, shown)
                }
                alt={`${shown} on ${template}`}
              />
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
