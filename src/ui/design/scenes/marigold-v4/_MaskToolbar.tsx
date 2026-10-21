// Selected option D, integrated into the full throwaway workflow.
import { useState } from "react";
import { EraserIcon } from "@phosphor-icons/react/dist/csr/Eraser";
import { PaintBrushIcon } from "@phosphor-icons/react/dist/csr/PaintBrush";
import { EyeIcon } from "@phosphor-icons/react/dist/csr/Eye";
import { DotsThreeIcon } from "@phosphor-icons/react/dist/csr/DotsThree";
import type { MaskControls } from "./_MarigoldScreen";
type Props = { controls: MaskControls };

export function MaskToolbar({ controls: c }: Props) {
  const [open, setOpen] = useState(false);
  const editing = c.tool !== "placement";
  return (
    <div
      className="mg-maskbar"
      onKeyDown={(e) => {
        if (e.key === "Escape") setOpen(false);
      }}
    >
      <span className="mg-mask-legend">
        <i className={c.showMask ? "" : "is-hidden"} />
        {c.showMask ? "Red = hidden print" : "Mask overlay hidden"}
      </span>
      <span className="mg-mask-spacer" />
      <button
        className="mg-mask-icon"
        aria-label="Show mask"
        title={c.showMask ? "Hide mask overlay" : "Show mask overlay"}
        aria-pressed={c.showMask}
        onClick={() => c.setShowMask(!c.showMask)}
      >
        <EyeIcon />
      </button>
      <div className="mg-mask-more">
        <button
          className="mg-mask-icon"
          aria-label="Mask actions"
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
      <button
        className={editing ? "mg-mask-done" : "mg-mask-edit"}
        onClick={() => {
          c.setTool(editing ? "placement" : "exclude");
          if (editing) c.setShowMask(false);
          setOpen(false);
        }}
      >
        {editing ? "Done" : "Edit mask"}
      </button>
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
    </div>
  );
}
