import { EraserIcon } from "@phosphor-icons/react/dist/csr/Eraser";
import { PaintBrushIcon } from "@phosphor-icons/react/dist/csr/PaintBrush";
export interface MaskControls {
  editing: boolean;
  setEditing: (value: boolean) => void;
  mode: "mask" | "unmask";
  setMode: (value: "mask" | "unmask") => void;
  diameter: number;
  setDiameter: (value: number) => void;
  canEdit: boolean;
  canUndo: boolean;
  undo: () => void;
  reset: () => void;
}
/** The dock under the photo. Only "Edit mask" until editing starts; then the
 * brushes, Undo, Reset and Done. */
export function MaskBrushDock({ controls: c }: { controls: MaskControls }) {
  if (!c.editing) {
    return (
      <div className="mg-mask-dock">
        <button
          type="button"
          className="mg-mask-edit"
          disabled={!c.canEdit}
          title={!c.canEdit ? "Prepare the template to create an editable mask" : undefined}
          onClick={() => c.setEditing(true)}
        >
          Edit mask
        </button>
      </div>
    );
  }
  return (
    <div
      className="mg-mask-dock"
      role="toolbar"
      aria-label="Mask brushes"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          c.setEditing(false);
        }
      }}
    >
      <span className="mg-mask-legend">
        <i />
        Red = hidden print
      </span>
      <button type="button" aria-pressed={c.mode === "mask"} onClick={() => c.setMode("mask")}>
        <PaintBrushIcon />
        Mask
      </button>
      <button type="button" aria-pressed={c.mode === "unmask"} onClick={() => c.setMode("unmask")}>
        <EraserIcon />
        Unmask
      </button>
      <span className="mg-mask-divider" />
      <label className="mg-mask-size">
        {" "}
        <input
          aria-label="Brush size"
          type="range"
          min={8}
          max={80}
          value={c.diameter}
          onChange={(e) => c.setDiameter(Number(e.target.value))}
        />
        <span>{c.diameter}px</span>
      </label>
      <span className="mg-mask-divider" />
      <button type="button" aria-label="Undo brush stroke" disabled={!c.canUndo} onClick={c.undo}>
        Undo
      </button>
      <button type="button" aria-label="Reset mask" disabled={!c.canEdit} onClick={c.reset}>
        Reset
      </button>
      <button type="button" className="mg-mask-done" onClick={() => c.setEditing(false)}>
        Done
      </button>
    </div>
  );
}
