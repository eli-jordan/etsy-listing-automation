import { useState, type ReactNode } from "react";
import { artwork, foldedBox, identity, limits, photos } from "./_fixtures";
import { PositionGlyph } from "./_EditorFrame";
import { deg, isIdentity, partsAtLimit, pct, type Pose } from "./_geometry";
import { PositionStage, type Layer } from "./_PositionStage";

/** "92% · up 6%" -- the pose in the words the chip uses. */
export function summary(p: Pose): string {
  const parts = [pct(p.scale)];
  if (Math.round(p.dy * 100)) parts.push(`${p.dy < 0 ? "up" : "down"} ${pct(Math.abs(p.dy))}`);
  if (Math.round(p.dx * 100)) parts.push(`${p.dx < 0 ? "left" : "right"} ${pct(Math.abs(p.dx))}`);
  if (Math.round(p.rotation)) parts.push(deg(p.rotation));
  return parts.join(" · ");
}

/** What a handle that stopped says, in words; null when nothing is at a limit. */
export function limitHint(p: Pose): string | null {
  const at = partsAtLimit(p, limits);
  if (at.has("scale")) return p.scale > 1 ? "Largest size allowed" : "Smallest size allowed";
  if (at.has("rotation")) return "Most tilt allowed";
  if (at.has("dx") || at.has("dy")) return "As far as it can move";
  return null;
}

/** The quiet on/off for Position mode: the app's own switch, with a label. */
export function PositionSwitch({ on, onToggle, disabled, title }: { on: boolean; onToggle?: () => void; disabled?: boolean; title?: string }) {
  return (
    <label className={disabled ? "tp-switch tp-switch--disabled" : "tp-switch"} title={title}>
      <span>Adjust position</span>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label="Adjust position"
        className={on ? "switch switch--on" : "switch"}
        disabled={disabled}
        onClick={onToggle}
      >
        <span className="switch__knob" />
      </button>
    </label>
  );
}

/** Where the design sits now: the template's own box, or this listing's. */
export function PositionChip({ pose, invalid }: { pose: Pose; invalid?: boolean }) {
  if (invalid)
    return (
      <span className="tp-chip tp-chip--danger">
        <PositionGlyph /> Outside the limits · blocks deploy
      </span>
    );
  if (isIdentity(pose)) return <span className="tp-chip tp-chip--muted">Template position</span>;
  return (
    <span className="tp-chip" title="This listing positions the design on this template">
      <PositionGlyph /> {summary(pose)}
    </span>
  );
}

interface PaneProps {
  initial: Pose;
  editing?: boolean;
  title?: string;
  path?: string;
}

const SIZE = { w: 480, h: 480 };

/**
 * The preview pane for one template entry. Off: the composite at the
 * listing's position. On: handles on the stage, the template's own box as a
 * dashed ghost, and the chip tracking the drag. Changes save like every
 * other editor field -- there is no Done.
 */
export function PositionPane({
  initial,
  editing = false,
  title = "cc1717-folded · ivory",
  path = "mockup-templates/cc1717-folded/ivory.png",
}: PaneProps) {
  const [pose, setPose] = useState(initial);
  const [on, setOn] = useState(editing);
  const hint = limitHint(pose);
  const layers: Layer[] = [{ id: "main", box: foldedBox, pose, label: "Design" }];

  return (
    <>
      <div className="preview-stage preview-stage--large">
        <PositionStage
          photo={photos.ivory}
          size={SIZE}
          artwork={artwork}
          layers={layers}
          editing={on ? "main" : null}
          ghost
          atLimit={on && hint !== null}
          limits={limits}
          onChange={(_, p) => setPose(p)}
        />
      </div>
      <Foot
        title={title}
        path={path}
        note={on ? (hint ?? "Applies to all 4 cc1717-folded colours in this listing") : null}
        warn={on && hint !== null}
        chip={<PositionChip pose={pose} />}
        reset={on && !isIdentity(pose) ? () => setPose(identity) : undefined}
        toggle={<PositionSwitch on={on} onToggle={() => setOn((v) => !v)} />}
      />
    </>
  );
}

/** The preview foot: title and path, a note line, then the position controls. */
export function Foot({
  title,
  path,
  note,
  warn,
  chip,
  reset,
  resetLabel = "Reset to template",
  extra,
  toggle,
}: {
  title: string;
  path: string;
  note?: string | null;
  warn?: boolean;
  chip: ReactNode;
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
        {chip}
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
