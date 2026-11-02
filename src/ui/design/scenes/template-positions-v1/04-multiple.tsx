import { useState } from "react";
import { EditorFrame } from "./_EditorFrame";
import { artwork, identity, limits, pairBoxes, pairPhoto, photos, type ReelItem } from "./_fixtures";
import { isIdentity, type Pose } from "./_geometry";
import { PositionStage } from "./_PositionStage";
import { Readout } from "./_Readout";

export const meta = {
  title: "4 · Multiple template — per placement · v1",
  viewport: "laptop",
  description: "cc1717-colour-pair has two placements; each is positioned on its own. The other renders dimmed and is click-to-select.",
};

const reel: ReelItem[] = [
  { label: "cc1717-folded · ivory", photo: photos.ivory, positioned: true },
  { label: "cc1717-colour-pair", photo: photos.yam, positioned: true },
  { label: "cc1717-hanging-on-fence · bay", photo: photos.bay },
];

export default function Frame() {
  const [selected, setSelected] = useState("left-shirt");
  const [poses, setPoses] = useState<Record<string, Pose>>({
    "left-shirt": { scale: 0.9, dx: 0, dy: -0.04, rotation: -3 },
    "right-shirt": identity,
  });
  const current = poses[selected];
  const set = (id: string, p: Pose) => setPoses((all) => ({ ...all, [id]: p }));

  const pane = (
    <>
      <div className="preview-stage preview-stage--large tp-stage-box--editing">
        <PositionStage
          photo={pairPhoto}
          size={{ w: 960, h: 480 }}
          artwork={artwork}
          layers={pairBoxes.map((b) => ({ id: b.id, box: b.box, pose: poses[b.id], label: `${b.id} · ${b.colour}` }))}
          editing={selected}
          ghost
          limits={limits}
          onChange={set}
          onSelect={setSelected}
        />
      </div>
      <div className="tp-bar" role="group" aria-label="Placement position">
        <div className="tp-bar__lede">
          <strong>Position on cc1717-colour-pair</strong>
          <div className="seg tp-placements" role="radiogroup" aria-label="Placement">
            {pairBoxes.map((b) => (
              <button
                key={b.id}
                type="button"
                role="radio"
                aria-checked={selected === b.id}
                className={selected === b.id ? "seg-opt seg-opt--on" : "seg-opt"}
                onClick={() => setSelected(b.id)}
              >
                {b.id}
                {!isIdentity(poses[b.id]) && " ·  custom"}
              </button>
            ))}
          </div>
          <span>Each placement keeps its own position</span>
        </div>
        <Readout pose={current} limits={limits} layout="row" />
        <div className="tp-bar__actions">
          <button type="button" className="btn-like btn-like--ghost btn-sm" disabled={isIdentity(current)} onClick={() => set(selected, identity)}>
            Reset {selected}
          </button>
          <button type="button" className="btn-like btn-like--ghost btn-sm">
            Cancel
          </button>
          <button type="button" className="btn-like btn-like--primary btn-sm">
            Done
          </button>
        </div>
      </div>
    </>
  );

  return <EditorFrame pane={pane} reel={reel} selected={1} />;
}
