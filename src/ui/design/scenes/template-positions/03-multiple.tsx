import { useState } from "react";
import { EditorFrame } from "./_EditorFrame";
import { artwork, identity, limits, pairBoxes, pairPhoto } from "./_fixtures";
import { isIdentity, type Pose } from "./_geometry";
import { Foot, PositionSwitch } from "./_panes";
import { PositionStage } from "./_PositionStage";

export const meta = {
  title: "3 · Multiple template — per placement",
  viewport: "laptop",
  description: "cc1717-colour-pair has two placements, each positioned on its own; click the dimmed box to switch. The ivory tile goes back to frame 1.",
};

export default function Frame() {
  const [on, setOn] = useState(true);
  const [selected, setSelected] = useState("left-shirt");
  const [poses, setPoses] = useState<Record<string, Pose>>({
    "left-shirt": { scale: 0.9, dx: 0, dy: -0.04, rotation: -3 },
    "right-shirt": identity,
  });
  const current = poses[selected];
  const set = (id: string, p: Pose) => setPoses((all) => ({ ...all, [id]: p }));

  const pane = (
    <>
      <div className="preview-stage preview-stage--large">
        <PositionStage
          photo={pairPhoto}
          size={{ w: 960, h: 480 }}
          artwork={artwork}
          layers={pairBoxes.map((b) => ({ id: b.id, box: b.box, pose: poses[b.id], label: b.id }))}
          editing={on ? selected : null}
          ghost
          limits={limits}
          onChange={set}
          onSelect={setSelected}
        />
      </div>
      <Foot
        title="cc1717-colour-pair"
        path="mockup-templates/cc1717-colour-pair/scene.png"
        note={on ? "Click the other shirt to switch" : null}
        reset={on && !isIdentity(current) ? () => set(selected, identity) : undefined}
        resetLabel={`Reset ${selected}`}
        toggle={<PositionSwitch on={on} onToggle={() => setOn((v) => !v)} />}
      />
    </>
  );

  return <EditorFrame pane={pane} selected={1} />;
}
