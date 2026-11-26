import { useEffect, useMemo, useState } from "react";
import { getTemplateSwatch, listTemplates } from "../../api/calibrator";
import {
  listGarmentProfiles,
  listingDesignThumbnailUrl,
  listListingDesigns,
} from "../../api/listings";
import { usePreloadedPictures } from "../../hooks/usePreloadedPictures";
import { type Artwork, refName, sceneSource, templatePicture } from "../../media";
import type {
  DesignMap,
  GarmentProfileSummary,
  ListingDesignSummary,
  ListingDetail,
  TemplateSummary,
} from "../../types";
import { ArtworkPicker } from "./ArtworkPicker";
import {
  automatic,
  canHaveOwnDesign,
  cap,
  clothFor,
  isLinked,
  listNames,
  pickForColour,
  resolve,
  toneLabel,
  type Tone,
} from "./artwork";
import { mediaLostBy, selectColours, selectGarmentProfile } from "./colourSelection";
import { PrintsCard } from "./PrintsCard";
import { useIsPhone } from "../../phone/usePhone";

interface Props {
  detail: ListingDetail;
  onUpdate: (patch: Record<string, unknown>) => void;
  previewed: string | null;
  onPreview: (colour: string) => void;
  onChooseSlot?: (tone: Tone) => void;
  artwork?: Artwork | null;
}

/** The garment profile's colour-matrix, used to judge colours before the
 * listing has picked its Etsy images. Not a `media:` default. The
 * templates list is only consulted to refuse a name we *know* is not
 * colour-matrix -- a new listing must not wait on GET /api/templates
 * (or on a colour-matrix entry in `media:`) before the stage can render. */
function previewTemplate(
  profile: GarmentProfileSummary | undefined,
  templates: TemplateSummary[],
): string | null {
  const name = profile?.preview_template;
  if (!name) return null;
  const known = templates.find((t) => t.name === name);
  if (known !== undefined && known.kind !== "colour-matrix") return null;
  return name;
}

export function VariantsTab({
  detail,
  onUpdate,
  previewed,
  onPreview,
  onChooseSlot = () => undefined,
  artwork,
}: Props) {
  const [profiles, setProfiles] = useState<GarmentProfileSummary[]>([]);
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [library, setLibrary] = useState<ListingDesignSummary[]>([]);
  const [fetchedSwatches, setFetchedSwatches] = useState<{
    template: string;
    hexes: Record<string, string>;
  } | null>(null);
  const [status, setStatus] = useState("");
  const [picking, setPicking] = useState<string | null>(null);
  const phone = useIsPhone();

  useEffect(() => {
    listListingDesigns()
      .then(setLibrary)
      .catch(() => setLibrary([]));
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

  const shown =
    previewed !== null && colourNames.includes(previewed)
      ? previewed
      : (detail.colors[0] ?? colourNames[0] ?? null);

  const template = previewTemplate(profile, templates);
  const ownArtwork = artwork === undefined;
  const scene = ownArtwork ? sceneSource(detail.name, detail.design_content_hash) : artwork;
  const tones: Record<string, Tone> = profile?.colors ?? {};

  // Every colour's stage picture, fetched into the browser cache in list
  // order while the seller looks at the first: each is a full-size render
  // the first time, and judging which colours suit a design means clicking
  // through most of them.
  usePreloadedPictures(
    template === null ? [] : colourNames.map((colour) => templatePicture(template, colour, scene)),
  );

  useEffect(() => {
    if (template === null) return;
    let current = true;
    const fetches = colourNames.map((colour) =>
      getTemplateSwatch(template, colour)
        .then((hex) => [colour, hex] as const)
        .catch(() => null),
    );
    void Promise.all(fetches).then((results) => {
      if (!current) return;
      setFetchedSwatches({
        template,
        hexes: Object.fromEntries(results.filter((r) => r !== null)),
      });
    });
    return () => {
      current = false;
    };
  }, [template, colourNames]);
  const swatches = fetchedSwatches?.template === template ? fetchedSwatches.hexes : NO_SWATCHES;

  /** Reports what else the edit took with it: a bulk switch can drop a reel
   * somebody spent a while building, on a different tab. */
  function setColours(next: string[]) {
    setStatus(lostMediaStatus(mediaLostBy(detail, next)));
    onUpdate(selectColours(detail, next));
  }

  function pickOwn(colour: string, ref: string) {
    onUpdate({ design: pickForColour(detail.design, colour, ref) });
    setPicking(null);
    onPreview(colour);
  }

  function toggleColour(colour: string, enabled: boolean) {
    setColours(enabled ? [...detail.colors, colour] : detail.colors.filter((c) => c !== colour));
  }

  function pickProfile(name: string) {
    const chosen = profiles.find((p) => p.name === name);
    const colours = chosen === undefined ? [] : Object.keys(chosen.colors).sort();
    setStatus(lostMediaStatus(mediaLostBy(detail, colours)));
    onUpdate(selectGarmentProfile(detail, name, colours));
  }

  function onlyShade(shade: "dark" | "light") {
    if (!profile) return;
    setColours(colourNames.filter((colour) => profile.colors[colour] === shade));
  }

  const hasShades = profile !== undefined && Object.keys(profile.colors).length > 0;
  const ownable = ownArtwork && canHaveOwnDesign(detail.design);

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
            const file = resolvedFile(detail.design, colour, tones);
            const own = (detail.design[colour] ?? null) !== null;
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
                  onClick={() => onPreview(colour)}
                >
                  {swatches[colour] && (
                    <span
                      className="color-row__swatch"
                      style={{ background: swatches[colour] }}
                      aria-hidden="true"
                    />
                  )}
                  <span className="color-row__name">{colour}</span>
                  {own && enabled && (
                    <span className="tag tag-accent-2 color-row__own">own design</span>
                  )}
                </button>
                {enabled && ownable && profile !== undefined && (
                  <button
                    type="button"
                    className={[
                      "color-row__chip",
                      own ? "color-row__chip--own" : "",
                      file === null ? "color-row__chip--empty" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    style={
                      file !== null
                        ? { background: clothFor(colour, swatches[colour], detail.design, tones) }
                        : undefined
                    }
                    aria-label={`Select different design for ${cap(colour)}`}
                    title="Select different design"
                    onClick={() => {
                      onPreview(colour);
                      setPicking(colour);
                    }}
                  >
                    {file !== null && <img src={listingDesignThumbnailUrl(refName(file))} alt="" />}
                  </button>
                )}
                {classification ? (
                  <span
                    className={classification === "dark" ? "tag tag-neutral" : "tag tag-accent"}
                  >
                    {classification}
                  </span>
                ) : (
                  profile !== undefined && <span className="tag tag-dirty">no tone</span>
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
        <div className="preview-stage preview-stage--large">
          {template !== null && shown !== null ? (
            <img src={templatePicture(template, shown, scene)} alt={`${shown} on ${template}`} />
          ) : (
            <div className="image-placeholder">
              <span>Set preview_template on the garment profile to a colour-matrix mockup.</span>
            </div>
          )}
        </div>
        {/* Once the profile has loaded: before then every colour of a
            light/dark listing would read as having no tone. */}
        {ownArtwork && shown !== null && profile !== undefined && (
          <PrintsCard
            colour={shown}
            enabled={detail.colors.includes(shown)}
            design={detail.design}
            profile={detail.garment_profile}
            tones={tones}
            swatch={swatches[shown]}
            onChooseSlot={onChooseSlot}
            onPickColour={() => setPicking(shown)}
            onUseAutomatic={() => onUpdate({ design: automatic(detail.design, shown) })}
          />
        )}
        <p className="variants-preview__hint">
          {phone
            ? "Tap a colour to preview it — helps judge whether it suits the design."
            : "Click a colour to preview it — helps judge whether it suits the design."}
        </p>
        <p role="status" className="app__status">
          {status}
        </p>
      </div>

      {picking !== null && (
        <ArtworkPicker
          title={`Design for ${cap(picking)}`}
          hint={ownDesignHint(detail.design, picking, detail.colors, tones)}
          cloth={clothFor(picking, swatches[picking], detail.design, tones)}
          current={resolvedFile(detail.design, picking, tones)}
          library={library}
          onPick={(ref) => pickOwn(picking, ref)}
          onClose={() => setPicking(null)}
        />
      )}
    </div>
  );
}

function resolvedFile(
  design: DesignMap,
  colour: string,
  tones: Readonly<Record<string, Tone>>,
): string | null {
  const resolution = resolve(design, colour, tones);
  return resolution.kind === "resolved" ? resolution.ref : null;
}

function ownDesignHint(
  design: DesignMap,
  colour: string,
  enabled: readonly string[],
  tones: Readonly<Record<string, Tone>>,
): string {
  const linked = isLinked(design);
  const tone = tones[colour];
  const siblings = enabled.filter(
    (c) => c !== colour && (design[c] ?? null) === null && (linked || tones[c] === tone),
  );
  const only = `Only ${cap(colour)} changes.`;
  if (siblings.length === 0) return only;
  const toneDesign = tone === undefined ? "their design" : `the design for ${toneLabel(tone)}`;
  const what = linked ? "the design for all shirts" : toneDesign;
  return `${only} ${listNames(siblings)} keep${siblings.length === 1 ? "s" : ""} ${what}.`;
}

function lostMediaStatus(lost: number): string {
  if (lost === 0) return "";
  return `Removed ${lost} listing ${lost === 1 ? "image" : "images"} for colours no longer sold.`;
}

const NO_SWATCHES: Record<string, string> = {};
