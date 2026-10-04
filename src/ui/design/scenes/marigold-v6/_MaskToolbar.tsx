// Selected option D, integrated into the full throwaway workflow.
import { useState } from "react";
import { EraserIcon } from "@phosphor-icons/react/dist/csr/Eraser";
import { PaintBrushIcon } from "@phosphor-icons/react/dist/csr/PaintBrush";
import { DotsThreeIcon } from "@phosphor-icons/react/dist/csr/DotsThree";
import { BoundingBoxIcon } from "@phosphor-icons/react/dist/csr/BoundingBox";
import type { MaskControls } from "./_MarigoldScreen";
type Props = { controls: MaskControls };

export function MaskToolbar({ controls: c }: Props) {
  const editing = c.tool !== "placement";
  return (
    <div className="mg-maskbar">
      <div className="mg-box-control" title={c.showBox ? "Hide design box" : "Show design box"}>
        <BoundingBoxIcon aria-hidden="true" />
        <button
          className="mg-box-switch"
          role="switch"
          aria-label="Show design box"
          aria-checked={c.showBox}
          onClick={() => c.setShowBox(!c.showBox)}
        >
          <i />
        </button>
      </div>
      {editing && (
        <span className="mg-mask-legend">
          <i />
          Red = hidden print
        </span>
      )}
      <span className="mg-mask-spacer" />
      <button
        className={editing ? "mg-mask-done" : "mg-mask-edit"}
        onClick={() => {
          c.setTool(editing ? "placement" : "exclude");
          c.setShowMask(!editing);
        }}
      >
        {editing ? "Done" : "Edit mask"}
      </button>
    </div>
  );
}
function MaskActions({ controls: c }: Props) {
  const [open, setOpen] = useState(false);
  return (
    <div
      className="mg-mask-more"
      onKeyDown={(e) => {
        if (e.key === "Escape") setOpen(false);
      }}
    >
      <button
        className="mg-mask-icon"
        aria-label="Mask actions"
        title="Undo or reset mask"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <DotsThreeIcon />
      </button>
      {open && (
        <div className="mg-mask-menu">
          <button
            disabled={!c.canUndo}
            onClick={() => {
              c.undo();
              setOpen(false);
            }}
          >
            Undo brush stroke
          </button>
          <button
            onClick={() => {
              c.resetMask();
              setOpen(false);
            }}
          >
            Reset mask
          </button>
        </div>
      )}
    </div>
  );
}

export function MaskBrushDock({ controls: c }: Props) {
  return (
    <div
      className="mg-mask-dock"
      role="toolbar"
      aria-label="Mask brushes"
      onPointerDown={(e) => e.stopPropagation()}
      onPointerMove={(e) => e.stopPropagation()}
    >
      <button
        aria-pressed={c.tool === "exclude"}
        title="Mask: hide the print in brushed areas"
        onClick={() => c.setTool("exclude")}
      >
        <PaintBrushIcon />
        Mask
      </button>
      <button
        aria-pressed={c.tool === "restore"}
        title="Unmask: restore the print in brushed areas"
        onClick={() => c.setTool("restore")}
      >
        <EraserIcon />
        Unmask
      </button>
      <span className="mg-mask-divider" />
      <label className="mg-mask-size" title="Brush size">
        <i />
        <input
          aria-label="Brush size"
          type="range"
          min={8}
          max={80}
          value={c.brushSize}
          onChange={(e) => c.setBrushSize(+e.target.value)}
        />
        <span>{c.brushSize}px</span>
      </label>
      <MaskActions controls={c} />
    </div>
  );
}
