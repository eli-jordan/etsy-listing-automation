// Five throwaway layouts, with local interactions only.
import { useState } from "react";
import { ArrowCounterClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowCounterClockwise";
import { ArrowClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowClockwise";
import { PaintBrushIcon } from "@phosphor-icons/react/dist/csr/PaintBrush";
import { EraserIcon } from "@phosphor-icons/react/dist/csr/Eraser";
import { EyeIcon } from "@phosphor-icons/react/dist/csr/Eye";
import { DotsThreeIcon } from "@phosphor-icons/react/dist/csr/DotsThree";
import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import type { MaskControls } from "./_MarigoldScreen";
type Props = { controls: MaskControls };

function Legend({ shown }: { shown: boolean }) {
  return (
    <span className="mc-legend">
      <span className={shown ? "mc-swatch" : "mc-swatch mc-swatch--off"} />
      {shown ? "Blue = print allowed" : "Print area hidden"}
    </span>
  );
}
function Visibility({ controls: c, iconOnly = false }: Props & { iconOnly?: boolean }) {
  return (
    <button
      className={`btn btn-ghost mc-eye ${c.showMask ? "mc-eye--on" : ""}`}
      title={c.showMask ? "Hide print area overlay" : "Show print area overlay"}
      aria-label={c.showMask ? "Hide print area overlay" : "Show print area overlay"}
      aria-pressed={c.showMask}
      onClick={() => c.setShowMask(!c.showMask)}
    >
      <EyeIcon weight="bold" />
      {!iconOnly && "Show area"}
    </button>
  );
}
function Done({ controls: c }: Props) {
  return (
    <button className="btn btn-secondary mc-done" onClick={() => c.setTool("placement")}>
      <CheckIcon weight="bold" />
      Done
    </button>
  );
}
function HistoryMenu({ controls: c }: Props) {
  const [open, setOpen] = useState(false);
  return (
    <div
      className="mc-menu"
      onKeyDown={(e) => {
        if (e.key === "Escape") setOpen(false);
      }}
    >
      <button
        className="btn btn-ghost mc-icon"
        aria-label="More mask actions"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <DotsThreeIcon weight="bold" />
      </button>
      {open && (
        <div className="mc-dropdown" role="group" aria-label="Mask actions">
          <button className="btn btn-ghost" disabled={!c.canUndo} onClick={c.undo}>
            <ArrowCounterClockwiseIcon weight="bold" />
            Undo brush stroke
          </button>
          <button
            className="btn btn-ghost"
            onClick={() => {
              c.resetMask();
              setOpen(false);
            }}
          >
            <ArrowClockwiseIcon weight="bold" />
            Reset print area
          </button>
        </div>
      )}
    </div>
  );
}
function Brush({ controls: c, inline = false }: Props & { inline?: boolean }) {
  const [open, setOpen] = useState(false);
  const slider = (
    <label className="mc-brush-slider">
      Brush size{" "}
      <input
        type="range"
        aria-label="Brush size"
        min="8"
        max="80"
        value={c.brushSize}
        onChange={(e) => c.setBrushSize(Number(e.target.value))}
      />
      <span>{c.brushSize}px</span>
    </label>
  );
  if (inline) return slider;
  return (
    <div
      className="mc-brush"
      onKeyDown={(e) => {
        if (e.key === "Escape") setOpen(false);
      }}
    >
      <button className="btn btn-ghost" aria-expanded={open} onClick={() => setOpen(!open)}>
        Brush · {c.brushSize}px <CaretDownIcon weight="bold" />
      </button>
      {open && <div className="mc-brush-popover">{slider}</div>}
    </div>
  );
}
function BrushActions({ controls: c, compact = false }: Props & { compact?: boolean }) {
  return (
    <div
      className={`mc-brush-actions ${compact ? "mc-brush-actions--segmented" : ""}`}
      role="group"
      aria-label="Print area brushes"
    >
      <button
        className={`btn btn-secondary ${c.tool === "exclude" ? "mc-selected" : ""}`}
        aria-pressed={c.tool === "exclude"}
        onClick={() => c.setTool("exclude")}
      >
        <EraserIcon weight="bold" />
        Remove print
      </button>
      <button
        className={`btn btn-secondary ${c.tool === "restore" ? "mc-selected" : ""}`}
        aria-pressed={c.tool === "restore"}
        onClick={() => c.setTool("restore")}
      >
        <PaintBrushIcon weight="bold" />
        Allow print
      </button>
    </div>
  );
}

export function InlineToolbar({ controls: c }: Props) {
  const editing = c.tool !== "placement";
  return (
    <div className="mc-toolbar mc-inline">
      <div className="mc-line">
        {editing ? (
          <>
            <BrushActions controls={c} />
            <button
              className="btn btn-ghost mc-icon mc-push"
              title="Undo brush stroke"
              aria-label="Undo brush stroke"
              disabled={!c.canUndo}
              onClick={c.undo}
            >
              <ArrowCounterClockwiseIcon weight="bold" />
            </button>
            <Done controls={c} />
          </>
        ) : (
          <>
            <span className="mc-title">Print area</span>
            <button className="btn btn-secondary mc-push" onClick={() => c.setTool("exclude")}>
              Edit print area
            </button>
          </>
        )}
      </div>
      <div className="mc-line mc-detail-line">
        <Legend shown={c.showMask} />
        <div className="mc-push mc-line">
          {editing && <Brush controls={c} />}
          <Visibility controls={c} iconOnly />
          <HistoryMenu controls={c} />
        </div>
      </div>
    </div>
  );
}
export function TabbedToolbar({ controls: c }: Props) {
  const editing = c.tool !== "placement";
  return (
    <div className="mc-toolbar mc-tabbed">
      <div className="mc-line mc-mode-line">
        <div className="mc-mode-tabs" role="group" aria-label="Editor mode">
          <button
            className={!editing ? "mc-mode-active" : ""}
            onClick={() => c.setTool("placement")}
          >
            Design
          </button>
          <button className={editing ? "mc-mode-active" : ""} onClick={() => c.setTool("exclude")}>
            Print area
          </button>
        </div>
        <Visibility controls={c} />
      </div>
      {editing ? (
        <>
          <div className="mc-line">
            <BrushActions controls={c} compact />
            <div className="mc-line mc-push">
              <button
                className="btn btn-ghost mc-icon"
                aria-label="Undo brush stroke"
                title="Undo brush stroke"
                disabled={!c.canUndo}
                onClick={c.undo}
              >
                <ArrowCounterClockwiseIcon weight="bold" />
              </button>
              <button
                className="btn btn-ghost mc-icon"
                aria-label="Reset print area"
                title="Reset print area"
                onClick={c.resetMask}
              >
                <ArrowClockwiseIcon weight="bold" />
              </button>
            </div>
          </div>
          <div className="mc-line">
            <Legend shown={c.showMask} />
            <div className="mc-push">
              <Brush controls={c} />
            </div>
          </div>
        </>
      ) : (
        <p className="mc-guidance">
          Drag the design or its corners. Open Print area to adjust where ink can appear.
        </p>
      )}
    </div>
  );
}
export function MenuToolbar({ controls: c }: Props) {
  const editing = c.tool !== "placement";
  return (
    <div className="mc-toolbar mc-action-menu">
      <div className="mc-line">
        <span className="mc-title">{editing ? "Editing print area" : "Print area"}</span>
        <div className="mc-line mc-push">
          <Visibility controls={c} iconOnly />
          {editing ? (
            <Done controls={c} />
          ) : (
            <button className="btn btn-secondary" onClick={() => c.setTool("exclude")}>
              Edit print area
            </button>
          )}
        </div>
      </div>
      {editing && (
        <div className="mc-line">
          <label className="mc-select-label">
            <PaintBrushIcon weight="bold" />
            <select
              className="input"
              aria-label="Brush action"
              value={c.tool}
              onChange={(e) => c.setTool(e.target.value as "exclude" | "restore")}
            >
              <option value="exclude">Brush to remove print</option>
              <option value="restore">Brush to allow print</option>
            </select>
          </label>
          <Brush controls={c} />
          <HistoryMenu controls={c} />
        </div>
      )}
      <Legend shown={c.showMask} />
    </div>
  );
}
export function ActionToolbar({ controls: c }: Props) {
  const editing = c.tool !== "placement";
  return (
    <div className="mc-toolbar mc-named-actions">
      <div className="mc-line">
        <span className="mc-title">Where can the print appear?</span>
        <div className="mc-push">
          <Visibility controls={c} iconOnly />
        </div>
      </div>
      <div className="mc-action-pair" role="group" aria-label="Print area brushes">
        <button
          className={c.tool === "exclude" ? "mc-action mc-selected" : "mc-action"}
          aria-pressed={c.tool === "exclude"}
          onClick={() => c.setTool("exclude")}
        >
          <EraserIcon weight="bold" />
          <span>
            <strong>Hide print</strong>
            <small>Brush areas to keep clear</small>
          </span>
        </button>
        <button
          className={c.tool === "restore" ? "mc-action mc-selected" : "mc-action"}
          aria-pressed={c.tool === "restore"}
          onClick={() => c.setTool("restore")}
        >
          <PaintBrushIcon weight="bold" />
          <span>
            <strong>Bring print back</strong>
            <small>Brush cloth back in</small>
          </span>
        </button>
      </div>
      <div className="mc-line">
        <Legend shown={c.showMask} />
        <div className="mc-line mc-push">
          {editing && <Brush controls={c} />}
          <HistoryMenu controls={c} />
          {editing && <Done controls={c} />}
        </div>
      </div>
    </div>
  );
}
export function PopoverToolbar({ controls: c }: Props) {
  const editing = c.tool !== "placement";
  return (
    <div
      className="mc-toolbar mc-popover-editor"
      onKeyDown={(e) => {
        if (e.key === "Escape") c.setTool("placement");
      }}
    >
      <div className="mc-line">
        <div className="mc-summary">
          <span className="mc-title">Print area</span>
          <Legend shown={c.showMask} />
        </div>
        <div className="mc-line mc-push">
          <Visibility controls={c} iconOnly />
          <button
            className={`btn ${editing ? "btn-primary" : "btn-secondary"}`}
            aria-expanded={editing}
            onClick={() => c.setTool(editing ? "placement" : "exclude")}
          >
            Adjust area <CaretDownIcon weight="bold" />
          </button>
        </div>
      </div>
      {editing && (
        <div className="mc-editor-popover" role="group" aria-label="Adjust print area">
          <div className="mc-popover-head">
            <strong>Adjust print area</strong>
            <span>Brush on the image to correct it.</span>
          </div>
          <label className="mc-radio-action">
            <input
              type="radio"
              name="popover-action"
              checked={c.tool === "exclude"}
              onChange={() => c.setTool("exclude")}
            />
            <span>
              <strong>Remove print</strong>
              <small>Keep artwork off this area</small>
            </span>
          </label>
          <label className="mc-radio-action">
            <input
              type="radio"
              name="popover-action"
              checked={c.tool === "restore"}
              onChange={() => c.setTool("restore")}
            />
            <span>
              <strong>Allow print</strong>
              <small>Make this area printable again</small>
            </span>
          </label>
          <Brush controls={c} inline />
          <div className="mc-line mc-popover-history">
            <button className="btn btn-ghost" disabled={!c.canUndo} onClick={c.undo}>
              <ArrowCounterClockwiseIcon weight="bold" />
              Undo
            </button>
            <button className="btn btn-ghost" onClick={c.resetMask}>
              Reset area
            </button>
            <Done controls={c} />
          </div>
        </div>
      )}
    </div>
  );
}
