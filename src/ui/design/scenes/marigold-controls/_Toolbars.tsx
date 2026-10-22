import { useState } from "react";
import { EraserIcon } from "@phosphor-icons/react/dist/csr/Eraser";
import { PaintBrushIcon } from "@phosphor-icons/react/dist/csr/PaintBrush";
import { EyeIcon } from "@phosphor-icons/react/dist/csr/Eye";
import { ArrowCounterClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowCounterClockwise";
import { DotsThreeIcon } from "@phosphor-icons/react/dist/csr/DotsThree";
import type { MaskControls } from "../marigold-v3/_MarigoldScreen";
type Props = { controls: MaskControls };
function Visibility({ controls: c }: Props) {
  return (
    <button
      className="mc-icon"
      title="Show or hide mask"
      aria-label="Show mask"
      aria-pressed={c.showMask}
      onClick={() => c.setShowMask(!c.showMask)}
    >
      <EyeIcon />
    </button>
  );
}
function History({ controls: c }: Props) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mc-more">
      <button
        className="mc-icon"
        aria-label="Mask actions"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <DotsThreeIcon />
      </button>
      {open && (
        <div className="mc-menu">
          <button disabled={!c.canUndo} onClick={c.undo}>
            Undo stroke
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
function Size({ controls: c }: Props) {
  return (
    <label className="mc-size" title="Brush size">
      <span className="mc-dot" />
      <input
        aria-label="Brush size"
        type="range"
        min={8}
        max={80}
        value={c.brushSize}
        onChange={(e) => c.setBrushSize(+e.target.value)}
      />
      <span>{c.brushSize}</span>
    </label>
  );
}
function Actions({ controls: c, vertical = false }: Props & { vertical?: boolean }) {
  return (
    <div className={`mc-actions ${vertical ? "mc-vertical" : ""}`}>
      <button
        aria-pressed={c.tool === "exclude"}
        title="Remove from printable area"
        onClick={() => c.setTool("exclude")}
      >
        <EraserIcon />
        <span>Remove</span>
      </button>
      <button
        aria-pressed={c.tool === "restore"}
        title="Add to printable area"
        onClick={() => c.setTool("restore")}
      >
        <PaintBrushIcon />
        <span>Add back</span>
      </button>
    </div>
  );
}
function Done({ controls: c }: Props) {
  return (
    <button className="mc-done" onClick={() => c.setTool("placement")}>
      Done
    </button>
  );
}
function Legend() {
  return (
    <span className="mc-legend">
      <i />
      Red = printable area
    </span>
  );
}
function Rest({ controls: c }: Props) {
  return (
    <div className="mc-rest">
      <Legend />
      <div className="mc-spacer" />
      <Visibility controls={c} />
      <button onClick={() => c.setTool("exclude")}>Edit mask</button>
    </div>
  );
}

export function InlineToolbar({ controls: c }: Props) {
  if (c.tool === "placement") return <Rest controls={c} />;
  return (
    <div className="mc-toolbar mc-single">
      <Actions controls={c} />
      <span className="mc-divider" />
      <Size controls={c} />
      <div className="mc-spacer" />
      <Visibility controls={c} />
      <History controls={c} />
      <Done controls={c} />
      <div className="mc-canvas-legend">
        <Legend />
      </div>
    </div>
  );
}

export function TabbedToolbar({ controls: c }: Props) {
  if (c.tool === "placement") return <Rest controls={c} />;
  return (
    <div className="mc-toolbar mc-rail">
      <div className="mc-heading">
        <strong>Edit mask</strong>
        <div className="mc-spacer" />
        <Legend />
        <Visibility controls={c} />
        <Done controls={c} />
      </div>
      <div className="mc-tool-rail">
        <Actions controls={c} vertical />
        <span className="mc-rail-rule" />
        <button
          className="mc-rail-size"
          title="Cycle brush size"
          onClick={() => c.setBrushSize(c.brushSize >= 60 ? 15 : c.brushSize + 15)}
        >
          <span className="mc-dot" />
          {c.brushSize}px
        </button>
        <button
          className="mc-icon"
          title="Undo stroke"
          aria-label="Undo stroke"
          disabled={!c.canUndo}
          onClick={c.undo}
        >
          <ArrowCounterClockwiseIcon />
        </button>
        <History controls={c} />
      </div>
    </div>
  );
}

export function MenuToolbar({ controls: c }: Props) {
  if (c.tool === "placement") return <Rest controls={c} />;
  return (
    <div className="mc-toolbar mc-guided">
      <div className="mc-heading">
        <span className="mc-step">Mask</span>
        <span>Brush to</span>
        <select
          aria-label="Brush action"
          value={c.tool}
          onChange={(e) => c.setTool(e.target.value as "exclude" | "restore")}
        >
          <option value="exclude">remove printable area</option>
          <option value="restore">add printable area back</option>
        </select>
        <div className="mc-spacer" />
        <Done controls={c} />
      </div>
      <div className="mc-guided-options">
        <Legend />
        <div className="mc-spacer" />
        <Size controls={c} />
        <Visibility controls={c} />
        <History controls={c} />
      </div>
    </div>
  );
}

export function ActionToolbar({ controls: c }: Props) {
  if (c.tool === "placement") return <Rest controls={c} />;
  return (
    <div className="mc-toolbar mc-docked">
      <div className="mc-heading">
        <Legend />
        <div className="mc-spacer" />
        <Visibility controls={c} />
        <History controls={c} />
        <Done controls={c} />
      </div>
      <div className="mc-dock">
        <Actions controls={c} />
        <span className="mc-divider" />
        <Size controls={c} />
      </div>
    </div>
  );
}

export function PopoverToolbar({ controls: c }: Props) {
  if (c.tool === "placement") return <Rest controls={c} />;
  return (
    <div className="mc-toolbar mc-ribbon">
      <div className="mc-ribbon-label">
        <strong>Editing mask</strong>
        <Legend />
      </div>
      <div className="mc-ribbon-controls">
        <div className="mc-ribbon-group">
          <small>BRUSH</small>
          <Actions controls={c} />
        </div>
        <div className="mc-ribbon-group">
          <small>SIZE</small>
          <div className="mc-presets">
            {[15, 30, 60].map((n, i) => (
              <button
                key={n}
                aria-label={`${n} pixel brush`}
                aria-pressed={c.brushSize === n}
                onClick={() => c.setBrushSize(n)}
              >
                <i style={{ width: 6 + i * 4, height: 6 + i * 4 }} />
              </button>
            ))}
          </div>
        </div>
        <div className="mc-spacer" />
        <Visibility controls={c} />
        <History controls={c} />
        <Done controls={c} />
      </div>
    </div>
  );
}
