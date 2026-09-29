import { listingDesignThumbnailUrl } from "../../api/listings";
import { refName } from "../../media";
import type { DesignMap } from "../../types";
import {
  canHaveOwnDesign,
  cap,
  clothFor,
  resolve,
  toneLabel,
  wouldPrintAutomatically,
  type Tone,
} from "./artwork";

/**
 * "What this colour prints", under the Variants stage (interactions Part 1
 * §8, Part 2 §6).
 *
 * The stage shows the file; this says in words where it came from, because
 * resolution has three sources and depends on shared garment data, and a
 * seller who cannot see why a colour prints a file cannot fix it when it is
 * wrong. Its actions follow the state (Part 2 §6): a colour's own design
 * offers **Change** and **Use automatic design**, having already said what
 * automatic would print, so going back needs no confirmation; an empty slot
 * offers to fill the slot first, because that fixes every colour that needs
 * it at once; anything else offers the colour its own design. A colour with
 * no tone offers nothing -- tone is shared garment data, and an own design
 * does not stand in for it (spec: *Artwork resolution*).
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
  /** Opens the colour's own design picker. */
  onPickColour: () => void;
  /** Removes the colour's own design. */
  onAutomatic: () => void;
}

export function PrintsCard({
  colour,
  enabled,
  design,
  profile,
  tones,
  swatch,
  onChooseSlot,
  onPickColour,
  onAutomatic,
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
        why = `Its own design, for ${name} only.${automaticWouldPrint(
          wouldPrintAutomatically(design, colour, tones),
        )}`;
      } else {
        const slot = resolution.source === "on-light" ? "light" : "dark";
        why = `Automatic: the design for ${toneLabel(slot)}, because ${profile} marks ${colour} ${slot}.`;
      }
      break;
    }
  }

  const file = resolution.kind === "resolved" ? resolution.ref : null;
  const own = resolution.kind === "resolved" && resolution.source === "colour";
  return (
    <div
      className={
        resolution.kind === "unclassified" ? "color-prints color-prints--blocked" : "color-prints"
      }
    >
      {file !== null ? (
        <span
          className="color-prints__thumb"
          style={{ background: clothFor(colour, swatch, design, tones) }}
        >
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
      {resolution.kind !== "unclassified" && canHaveOwnDesign(design) && (
        <div className="color-prints__actions">
          {own ? (
            <>
              <button
                type="button"
                className="btn-like btn-sm color-prints__btn"
                onClick={onPickColour}
              >
                Change
              </button>
              <button
                type="button"
                className="btn-like btn-like--ghost btn-sm color-prints__btn"
                onClick={onAutomatic}
              >
                Use automatic design
              </button>
            </>
          ) : resolution.kind === "slot-empty" ? (
            <>
              <button
                type="button"
                className="btn-like btn-like--primary btn-sm color-prints__btn"
                onClick={() => onChooseSlot(resolution.tone)}
              >
                Choose design for {toneLabel(resolution.tone)}
              </button>
              <button
                type="button"
                className="btn-like btn-like--ghost btn-sm color-prints__btn"
                onClick={onPickColour}
              >
                Select different design for {name}
              </button>
            </>
          ) : (
            <button
              type="button"
              className="btn-like btn-sm color-prints__btn"
              onClick={onPickColour}
            >
              Select different design
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/** " Back on automatic it would print …" -- nothing when automatic prints
 * nothing, since there is then no file to name. */
function automaticWouldPrint(fallback: ReturnType<typeof resolve>): string {
  if (fallback.kind !== "resolved") return "";
  const slot =
    fallback.source === "on-light"
      ? `, the design for ${toneLabel("light")}`
      : fallback.source === "on-dark"
        ? `, the design for ${toneLabel("dark")}`
        : "";
  return ` Back on automatic it would print ${refName(fallback.ref)}${slot}.`;
}
