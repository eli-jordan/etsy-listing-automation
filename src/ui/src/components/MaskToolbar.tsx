import { BoundingBoxIcon } from "@phosphor-icons/react/dist/csr/BoundingBox";
import { DotsThreeIcon } from "@phosphor-icons/react/dist/csr/DotsThree";
import { EraserIcon } from "@phosphor-icons/react/dist/csr/Eraser";
import { PaintBrushIcon } from "@phosphor-icons/react/dist/csr/PaintBrush";
import { useState } from "react";
export interface MaskControls {
  editing: boolean;
  setEditing: (value: boolean) => void;
  showBox: boolean;
  setShowBox: (value: boolean) => void;
  mode: "mask" | "unmask";
  setMode: (value: "mask" | "unmask") => void;
  diameter: number;
  setDiameter: (value: number) => void;
  canEdit: boolean;
  canUndo: boolean;
  undo: () => void;
  reset: () => void;
}
export function MaskToolbar({ controls: c }: { controls: MaskControls }) {
  return (
    <div className="mg-maskbar">
      <div className="mg-box-control" title={c.showBox ? "Hide design box" : "Show design box"}>
        <BoundingBoxIcon aria-hidden="true" />
        <button
          type="button"
          className="mg-box-switch"
          role="switch"
          aria-label="Show design box"
          aria-checked={c.showBox}
          onClick={() => c.setShowBox(!c.showBox)}
        >
          <i />
        </button>
      </div>
      {c.editing && (
        <span className="mg-mask-legend">
          <i />
          Red = hidden print
        </span>
      )}
      <span className="mg-mask-spacer" />
      <button
        type="button"
        disabled={!c.canEdit}
        title={!c.canEdit ? "Prepare the template to create an editable mask" : undefined}
        className={c.editing ? "mg-mask-done" : "mg-mask-edit"}
        onClick={() => c.setEditing(!c.editing)}
      >
        {c.editing ? "Done" : "Edit mask"}
      </button>
    </div>
  );
}
export function MaskBrushDock({ controls: c }: { controls: MaskControls }) {
  const [menu, setMenu] = useState(false);
  return (
    <div
      className="mg-mask-dock"
      role="toolbar"
      aria-label="Mask brushes"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          setMenu(false);
          c.setEditing(false);
        }
      }}
    >
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
      <div className="mg-mask-more">
        <button
          type="button"
          className="mg-mask-icon"
          aria-label="Mask actions"
          aria-expanded={menu}
          onClick={() => setMenu(!menu)}
        >
          <DotsThreeIcon />
        </button>
        {menu && (
          <div className="mg-mask-menu">
            <button
              disabled={!c.canUndo}
              onClick={() => {
                c.undo();
                setMenu(false);
              }}
            >
              Undo brush stroke
            </button>
            <button
              onClick={() => {
                c.reset();
                setMenu(false);
              }}
            >
              Reset mask
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
