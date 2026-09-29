import { listingDesignThumbnailUrl } from "../../api/listings";
import { refName } from "../../media";
import type { DesignMap } from "../../types";
import { cap, isLinked, resolve, toneLabel, TILE, type Tone } from "./artwork";

/**
 * "What this colour prints", under the Variants stage (interactions Part 1
 * §8, Part 2 §6).
 *
 * The stage shows the file; this says in words where it came from, because
 * resolution has three sources and depends on shared garment data, and a
 * seller who cannot see why a colour prints a file cannot fix it when it is
 * wrong. Only the base-slot states offer an action here -- filling an empty
 * slot, which fixes every colour that needs it at once. A colour's own design
 * and its actions arrive with the colour-exception work (multi-artwork plan,
 * PR 3).
 */

interface Props {
  colour: string;
  enabled: boolean;
  design: DesignMap;
  profile: string;
  tones: Readonly<Record<string, Tone>>;
  /** The colour's real garment shade, when the swatch has been sampled. */
  swatch: string | undefined;
  /** Opens that slot's Recent designs panel in the strip above the tabs. */
  onChooseSlot: (tone: Tone) => void;
}

export function PrintsCard({
  colour,
  enabled,
  design,
  profile,
  tones,
  swatch,
  onChooseSlot,
}: Props) {
  const name = cap(colour);
  if (!enabled) {
    return (
      <p className="variants-preview__hint">
        {name} isn’t sold on this listing. Switch it on to choose what it prints.
      </p>
    );
  }

  const resolution = resolve(design, colour, tones);
  const tone = tones[colour];
  let title: string;
  let why: string;
  switch (resolution.kind) {
    case "unclassified":
      title = `${name} can’t pick a design yet`;
      why = `The ${profile} garment profile doesn’t say whether ${colour} is a light or dark shirt. Mark it in garment-profiles/${profile}.yaml — this listing can’t decide it.`;
      break;
    case "slot-empty":
      title = `${name} has nothing to print`;
      why = `It’s a ${resolution.tone} shirt, and no design for ${toneLabel(resolution.tone)} is chosen yet.`;
      break;
    case "no-design":
      title = `${name} has nothing to print`;
      why = "Choose a design above.";
      break;
    case "resolved": {
      title = `${name} prints ${refName(resolution.ref)}`;
      if (resolution.source === "default") {
        why = "Automatic: the one design for all shirts.";
      } else if (resolution.source === "colour") {
        why = `Its own design, for ${name} only.`;
      } else {
        const slot = resolution.source === "on-light" ? "light" : "dark";
        why = `Automatic: the design for ${toneLabel(slot)}, because ${profile} marks ${colour} ${slot}.`;
      }
      break;
    }
  }

  const file = resolution.kind === "resolved" ? resolution.ref : null;
  // Judged on its own cloth: the sampled swatch, else the tone's tile.
  const cloth = swatch ?? (tone === undefined || isLinked(design) ? TILE.neutral : TILE[tone]);
  return (
    <div
      className={
        resolution.kind === "unclassified" ? "color-prints color-prints--blocked" : "color-prints"
      }
    >
      {file !== null ? (
        <span className="color-prints__thumb" style={{ background: cloth }}>
          <img src={listingDesignThumbnailUrl(refName(file))} alt="" />
        </span>
      ) : (
        <span className="color-prints__thumb design-tile--empty" />
      )}
      <div className="color-prints__text">
        <div className="color-prints__title">{title}</div>
        <div className="color-prints__why">{why}</div>
        {file !== null && (
          <div className="color-prints__note">Listing Images and Printify use this same file.</div>
        )}
      </div>
      {resolution.kind === "slot-empty" && (
        <div className="color-prints__actions">
          <button
            type="button"
            className="btn-like btn-like--primary btn-sm color-prints__btn"
            onClick={() => onChooseSlot(resolution.tone)}
          >
            Choose design for {toneLabel(resolution.tone)}
          </button>
        </div>
      )}
    </div>
  );
}
