import { useState } from "react";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { listingDesignThumbnailUrl } from "../../api/listings";
import { refName } from "../../media";
import { listNames, TILE, toneLabel, type Tone } from "./artwork";

interface Props {
  light: string;
  dark: string;
  own: readonly string[];
  onKeep: (ref: string) => void;
  onCancel: () => void;
}

export function ChooseBaseDialog({ light, dark, own, onKeep, onCancel }: Props) {
  const [choice, setChoice] = useState<Tone | null>(null);
  const files: Record<Tone, string> = { light, dark };
  return (
    <ConfirmDialog
      title="Which design should every shirt print?"
      confirmLabel="Use one design"
      confirmDisabled={choice === null}
      className="choose-base"
      onConfirm={() => {
        if (choice !== null) onKeep(files[choice]);
      }}
      onCancel={onCancel}
    >
      <p className="choose-base__body">
        Pick the one to keep. The other stays in your design library.
      </p>
      <div className="choose-base__options" role="radiogroup" aria-label="Design to keep">
        {(["light", "dark"] as const).map((tone) => {
          const on = choice === tone;
          const name = refName(files[tone]);
          return (
            <button
              key={tone}
              type="button"
              role="radio"
              aria-checked={on}
              className={
                on
                  ? "template-card template-card--active choose-base__card"
                  : "template-card choose-base__card"
              }
              onClick={() => setChoice(tone)}
            >
              <span className="design-thumb design-tile" style={{ background: TILE[tone] }}>
                <img src={listingDesignThumbnailUrl(name)} alt="" />
              </span>
              <span className="choose-base__text">
                <span className="template-card__name">{name}</span>
                <span className="template-card__kind">Now the design for {toneLabel(tone)}</span>
              </span>
            </button>
          );
        })}
      </div>
      {own.length > 0 && (
        <p className="choose-base__note">
          {listNames(own)} keep{own.length === 1 ? "s its" : " their"} own design.
        </p>
      )}
    </ConfirmDialog>
  );
}
