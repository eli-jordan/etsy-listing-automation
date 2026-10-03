import { ShirtPreview } from "./ShirtPreview";
import {
  cap,
  resolve,
  resolvedDesign,
  toneLabel,
  type Base,
  type Colour,
  type Resolution,
  type Tone,
} from "./artwork";

/**
 * The real `VariantsTab` (src/pages/editor/VariantsTab.tsx), forked to take
 * fixture props instead of fetching, plus the multi-artwork parts: each row's
 * artwork chip and the "what this colour prints" card under the stage.
 * Everything else -- garment select, sizes, the shade buttons, rows, the
 * stage and its hint -- is the real markup.
 */
export function VariantsArtworkTab({
  profile,
  sizes,
  colours,
  base,
  previewed,
  status,
  onPreview,
  onToggle,
  onOnlyShade,
  onPickColour,
  onPickSlot,
  onAutomatic,
}: {
  profile: string;
  sizes: string[];
  colours: Colour[];
  base: Base;
  previewed: string;
  status: string;
  onPreview: (name: string) => void;
  onToggle: (name: string) => void;
  onOnlyShade: (tone: Tone) => void;
  onPickColour: (name: string) => void;
  onPickSlot: (tone: Tone) => void;
  onAutomatic: (name: string) => void;
}) {
  const shown = colours.find((c) => c.name === previewed) ?? colours[0];
  const enabled = colours.filter((c) => c.enabled).length;
  const hasShades = colours.some((c) => c.tone !== null);

  return (
    <div className="layout--variants">
      <fieldset>
        <legend>Variants</legend>

        <div className="field">
          <label htmlFor="variants-garment">Garment profile</label>
          <select id="variants-garment" defaultValue={profile}>
            <option value={profile}>{profile}</option>
          </select>
        </div>

        <div className="field">
          <label>Sizes</label>
          <div className="garment-card__sizes">
            {sizes.map((size) => (
              <span key={size} className="size-pill">
                {size}
              </span>
            ))}
          </div>
        </div>

        <div className="field">
          <div className="colors-panel__head">
            <label style={{ margin: 0 }}>Colours</label>
            <span className="colors-panel__count">
              {enabled} of {colours.length} included
            </span>
          </div>

          {hasShades && (
            <div className="shade-picker">
              <button type="button" className="btn-like btn-sm" onClick={() => onOnlyShade("dark")}>
                Dark
              </button>
              <button type="button" className="btn-like btn-sm" onClick={() => onOnlyShade("light")}>
                Light
              </button>
              <span className="shade-picker__hint">only these shades</span>
            </div>
          )}

          {colours.map((colour) => (
            <ColourRow
              key={colour.name}
              colour={colour}
              resolution={resolve(colour, base)}
              selected={colour.name === shown.name}
              onPreview={() => onPreview(colour.name)}
              onToggle={() => onToggle(colour.name)}
              onPick={() => onPickColour(colour.name)}
            />
          ))}
        </div>
      </fieldset>

      <div className="variants-preview">
        <div className="preview-stage preview-stage--large ma-stage">
          <ShirtPreview
            colour={shown.swatch}
            artwork={resolvedDesign(resolve(shown, base))?.url ?? null}
            label={`${shown.name} on the preview template`}
          />
        </div>
        <PrintsCard
          colour={shown}
          resolution={resolve(shown, base)}
          base={base}
          profile={profile}
          onPick={() => onPickColour(shown.name)}
          onPickSlot={onPickSlot}
          onAutomatic={() => onAutomatic(shown.name)}
        />
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

/* ── Variants rows and the card under the preview ─────────────────────────── */

function ColourRow({
  colour,
  resolution,
  selected,
  onPreview,
  onToggle,
  onPick,
}: {
  colour: Colour;
  resolution: Resolution;
  selected: boolean;
  onPreview: () => void;
  onToggle: () => void;
  onPick: () => void;
}) {
  const design = resolvedDesign(resolution);
  const rowClass = ["color-row", selected ? "color-row--selected" : "", colour.enabled ? "" : "color-row--off"]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={rowClass}>
      <button type="button" className="color-row__text" aria-label={`Preview ${colour.name}`} onClick={onPreview}>
        <span className="color-row__swatch" style={{ background: colour.swatch }} aria-hidden="true" />
        <span className="color-row__name">{colour.name}</span>
        {resolution.kind === "own" && colour.enabled && <span className="tag tag-accent-2 ma-own-tag">own design</span>}
      </button>
      {colour.enabled && (
        <button
          type="button"
          className={[
            "ma-chip",
            resolution.kind === "own" ? "ma-chip--own" : "",
            design === null ? "ma-chip--empty" : "",
          ]
            .filter(Boolean)
            .join(" ")}
          style={design !== null ? { background: colour.swatch } : undefined}
          aria-label={`Select different design for ${colour.name}`}
          title="Select different design"
          onClick={onPick}
        >
          {design !== null && <img src={design.url} alt="" />}
        </button>
      )}
      {colour.tone !== null ? (
        <span className={colour.tone === "dark" ? "tag tag-neutral" : "tag tag-accent"}>{colour.tone}</span>
      ) : (
        <span className="tag tag-dirty">no tone</span>
      )}
      <button
        type="button"
        role="switch"
        aria-checked={colour.enabled}
        aria-label={colour.name}
        className={colour.enabled ? "switch switch--on" : "switch"}
        onClick={onToggle}
      >
        <span className="switch__knob" />
      </button>
    </div>
  );
}

function PrintsCard({
  colour,
  resolution,
  base,
  profile,
  onPick,
  onPickSlot,
  onAutomatic,
}: {
  colour: Colour;
  resolution: Resolution;
  base: Base;
  profile: string;
  onPick: () => void;
  onPickSlot: (tone: Tone) => void;
  onAutomatic: () => void;
}) {
  const name = cap(colour.name);
  if (!colour.enabled) {
    return <p className="variants-preview__hint">{name} isn&rsquo;t sold on this listing. Switch it on to choose what it prints.</p>;
  }

  let title: string;
  let why: string;
  if (resolution.kind === "unclassified") {
    title = `${name} can’t pick a design yet`;
    why = `The ${profile} garment profile doesn’t say whether ${colour.name} is a light or dark shirt. Mark it in garment-profiles/${profile}.yaml — this listing can’t decide it.`;
  } else if (resolution.kind === "own") {
    const fallback = base.mode === "one" ? base.design : colour.tone === null ? null : base[colour.tone];
    title = `${name} prints ${resolution.design.name}`;
    why =
      `Its own design, for ${name} only.` +
      (fallback !== null
        ? ` Back on automatic it would print ${fallback.name}${base.mode === "light-dark" && colour.tone !== null ? `, the design for ${toneLabel(colour.tone)}` : ""}.`
        : "");
  } else if (resolution.design === null) {
    title = `${name} has nothing to print`;
    why =
      resolution.kind === "slot"
        ? `It’s a ${resolution.tone} shirt, and no design for ${toneLabel(resolution.tone)} is chosen yet.`
        : "Choose a design above.";
  } else {
    title = `${name} prints ${resolution.design.name}`;
    why =
      resolution.kind === "slot"
        ? `Automatic: the design for ${toneLabel(resolution.tone)}, because ${profile} marks ${colour.name} ${resolution.tone}.`
        : "Automatic: the one design for all shirts.";
  }

  const design = resolvedDesign(resolution);
  return (
    <div className={resolution.kind === "unclassified" ? "ma-prints ma-prints--blocked" : "ma-prints"}>
      {design !== null ? (
        <span className="ma-prints__thumb" style={{ background: colour.swatch }}>
          <img src={design.url} alt="" />
        </span>
      ) : (
        <span className="ma-prints__thumb ma-tile--empty" />
      )}
      <div className="ma-prints__text">
        <div className="ma-prints__title">{title}</div>
        <div className="ma-prints__why">{why}</div>
        {design !== null && <div className="ma-prints__note">Listing Images and Printify use this same file.</div>}
      </div>
      {resolution.kind !== "unclassified" && (
        <div className="ma-prints__actions">
          {resolution.kind === "own" ? (
            <>
              <button type="button" className="btn-like btn-sm ma-btn" onClick={onPick}>
                Change
              </button>
              <button type="button" className="btn-like btn-like--ghost btn-sm ma-btn" onClick={onAutomatic}>
                Use automatic design
              </button>
            </>
          ) : resolution.kind === "slot" && resolution.design === null ? (
            <>
              <button type="button" className="btn-like btn-like--primary btn-sm ma-btn" onClick={() => onPickSlot(resolution.tone)}>
                Choose design for {toneLabel(resolution.tone)}
              </button>
              <button type="button" className="btn-like btn-like--ghost btn-sm ma-btn" onClick={onPick}>
                Select different design for {name}
              </button>
            </>
          ) : (
            <button type="button" className="btn-like btn-sm ma-btn" onClick={onPick}>
              Select different design
            </button>
          )}
        </div>
      )}
    </div>
  );
}

