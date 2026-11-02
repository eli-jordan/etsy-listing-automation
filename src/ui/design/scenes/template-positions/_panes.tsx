import { useState, type ReactNode } from "react";
import { artwork, foldedBox, identity, limits, photos } from "./_fixtures";
import { isIdentity, type Pose } from "./_geometry";
import { PositionStage } from "./_PositionStage";

/**
 * The quiet on/off for Position mode: the app's own switch, with a label.
 * With `goto` it is a prototype link (play mode swaps frames); without, it
 * flips local state.
 */
export function PositionSwitch({ on, onToggle, goto }: { on: boolean; onToggle?: () => void; goto?: string }) {
  return (
    <label className="tp-switch">
      <span>Adjust position</span>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label="Adjust position"
        className={on ? "switch switch--on" : "switch"}
        data-goto={goto}
        onClick={goto ? undefined : onToggle}
      >
        <span className="switch__knob" />
      </button>
    </label>
  );
}

const SIZE = { w: 480, h: 480 };
const SCOPE = "Applies to all 4 cc1717-folded colours in this listing";

/**
 * The preview pane for one cc1717-folded entry. Off: the composite at the
 * listing's position. On: handles on the stage and the template's own box as
 * a dashed ghost. Changes save like every other editor field -- no Done.
 */
export function PositionPane({ initial, editing = false, switchGoto }: { initial: Pose; editing?: boolean; switchGoto: string }) {
  const [pose, setPose] = useState(initial);
  return (
    <>
      <div className="preview-stage preview-stage--large">
        <PositionStage
          photo={photos.ivory}
          size={SIZE}
          artwork={artwork}
          layers={[{ id: "main", box: foldedBox, pose, label: "Design" }]}
          editing={editing ? "main" : null}
          ghost
          limits={limits}
          onChange={(_, p) => setPose(p)}
        />
      </div>
      <Foot
        title="cc1717-folded · ivory"
        path="mockup-templates/cc1717-folded/ivory.png"
        note={editing ? SCOPE : null}
        reset={editing && !isIdentity(pose) ? () => setPose(identity) : undefined}
        toggle={<PositionSwitch on={editing} goto={switchGoto} />}
      />
    </>
  );
}

/** The preview foot: title and path (and a note) on the left; Reset and the
 * switch together on the right. */
export function Foot({
  title,
  path,
  note,
  warn,
  reset,
  resetLabel = "Reset to template",
  extra,
  toggle,
}: {
  title: string;
  path: string;
  note?: string | null;
  warn?: boolean;
  reset?: () => void;
  resetLabel?: string;
  extra?: ReactNode;
  toggle: ReactNode;
}) {
  return (
    <div className="preview-foot tp-foot">
      <span className="preview-meta">
        <span className="preview-meta__title">{title}</span>
        <span className="preview-meta__path">{path}</span>
        {note && <span className={warn ? "tp-note tp-note--warn" : "tp-note"}>{note}</span>}
      </span>
      <span className="tp-controls">
        {extra}
        {reset && (
          <button type="button" className="tp-link" onClick={reset}>
            {resetLabel}
          </button>
        )}
        {toggle}
      </span>
    </div>
  );
}
