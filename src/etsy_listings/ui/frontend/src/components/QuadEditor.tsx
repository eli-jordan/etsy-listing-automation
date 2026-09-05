import { useLayoutEffect, useRef, useState } from "react";
import type { BoundingBox, Point } from "../types";

const NUDGE_PX = 1;
const NUDGE_PX_FAST = 8;

interface Props {
  imageUrl: string;
  boxes: BoundingBox[];
  selectedIndex: number;
  onSelect: (index: number) => void;
  onChangeBox: (index: number, box: BoundingBox) => void;
  /** `multiple`-kind only. Given these, the canvas grows the box-editing
   * affordances 2a puts *on* it -- add, delete, and a right-click menu -- so
   * you never have to leave the photo to change what you are looking at. */
  onAddBox?: () => void;
  onDeleteSelected?: () => void;
  onDuplicateSelected?: () => void;
  onBringSelectedToFront?: () => void;
  /** How much box chrome to draw. Three states rather than a boolean because
   * 2a's two toggles mean different things: a chart's "show all outlines"
   * hides the *other* boxes while you keep working on one ("selected"), and a
   * colour set's "show placement outline" hides everything so you can judge
   * the render clean ("none"). */
  outlines?: "all" | "selected" | "none";
  /** Label for the selected box, shown with its extent. Explicitly admits
   * `undefined`: `exactOptionalPropertyTypes` is on, so "may be absent" and
   * "may be undefined" are different types here. */
  selectedLabel?: string | undefined;
}

/**
 * Draggable four-corner box overlaid on the (already-rendered) preview
 * image -- one or more of them. The selected box gets live drag handles; the
 * rest render dimmed and click-to-select (`multiple`-kind templates only
 * ever have more than one; `colour-matrix`/`single` pass a single-element
 * array and never show the selection chrome). The SVG's viewBox is set to
 * the image's natural pixel size, so screen-to-image coordinate mapping goes
 * through the SVG's own CTM rather than a hand-rolled scale factor --
 * correct regardless of how the browser scales the displayed image.
 */

interface Menu {
  /** Where the menu opens, in `.quad-editor` px. */
  x: number;
  y: number;
}

function menuAnchor(clientX: number, clientY: number, svg: SVGSVGElement | null): Menu {
  const host = svg?.getBoundingClientRect();
  return { x: clientX - (host?.left ?? 0), y: clientY - (host?.top ?? 0) };
}

/** The rectangle the menu has to stay inside: the nearest ancestor that clips
 * its overflow, or the viewport if nothing does.
 *
 * Not the canvas. The canvas is a child of `.app__preview`, which is
 * `overflow: hidden` and is often the *shorter* of the two -- so anything
 * measured against the canvas gets the vertical case wrong, which is exactly
 * the bug the first attempt at this shipped. */
function clipRect(from: HTMLElement): DOMRect {
  for (let el = from.parentElement; el && el !== document.body; el = el.parentElement) {
    const style = getComputedStyle(el);
    if (style.overflowX !== "visible" || style.overflowY !== "visible") {
      return el.getBoundingClientRect();
    }
  }
  return new DOMRect(0, 0, window.innerWidth, window.innerHeight);
}

/** Place the menu at the click, then pull it back inside the clipping box.
 *
 * Measured rather than guessed from which half was clicked: the menu is
 * ~90px tall and the preview pane can be barely more than that, so "past the
 * midpoint" answers the wrong question. Written to the node in a layout
 * effect, before paint, so there is no state churn and nothing is ever seen
 * in the wrong place.
 *
 * Left unfixed, `.app__preview`'s clipping cut two of the three items off a
 * menu opened on the rightmost box -- "Delete" was simply unreachable for the
 * last garment in a chart. */
function positionMenu(el: HTMLElement, menu: Menu): void {
  Object.assign(el.style, { left: `${menu.x}px`, top: `${menu.y}px` });
  const rect = el.getBoundingClientRect();
  const clip = clipRect(el);
  if (rect.right > clip.right) el.style.left = `${Math.max(0, menu.x - rect.width)}px`;
  if (rect.bottom > clip.bottom) el.style.top = `${Math.max(0, menu.y - rect.height)}px`;
}

export function QuadEditor({
  imageUrl,
  boxes,
  selectedIndex,
  onSelect,
  onChangeBox,
  onAddBox,
  onDeleteSelected,
  onDuplicateSelected,
  onBringSelectedToFront,
  outlines = "all",
  selectedLabel,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [naturalSize, setNaturalSize] = useState<[number, number] | null>(null);
  const [dragPointIndex, setDragPointIndex] = useState<number | null>(null);
  const [menu, setMenu] = useState<Menu | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (menu && menuRef.current) positionMenu(menuRef.current, menu);
  }, [menu]);

  function toImageSpace(clientX: number, clientY: number): Point | null {
    const svg = svgRef.current;
    if (!svg) return null;
    const ctm = svg.getScreenCTM();
    if (!ctm) return null;
    const point = svg.createSVGPoint();
    point.x = clientX;
    point.y = clientY;
    const transformed = point.matrixTransform(ctm.inverse());
    return { x: transformed.x, y: transformed.y };
  }

  function handlePointerDown(pointIndex: number) {
    return (event: React.PointerEvent<SVGCircleElement>) => {
      event.currentTarget.setPointerCapture(event.pointerId);
      setDragPointIndex(pointIndex);
    };
  }

  function handlePointerMove(event: React.PointerEvent<SVGSVGElement>) {
    if (dragPointIndex === null) return;
    const point = toImageSpace(event.clientX, event.clientY);
    if (!point) return;
    const box = boxes[selectedIndex];
    if (!box) return;
    const next = box.map((p, i) => (i === dragPointIndex ? point : p)) as BoundingBox;
    onChangeBox(selectedIndex, next);
  }

  function handlePointerUp() {
    setDragPointIndex(null);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if ((event.key === "Delete" || event.key === "Backspace") && onDeleteSelected) {
      event.preventDefault();
      onDeleteSelected();
      return;
    }
    const box = boxes[selectedIndex];
    if (!box) return;
    const step = event.shiftKey ? NUDGE_PX_FAST : NUDGE_PX;
    let dx = 0;
    let dy = 0;
    if (event.key === "ArrowLeft") dx = -step;
    else if (event.key === "ArrowRight") dx = step;
    else if (event.key === "ArrowUp") dy = -step;
    else if (event.key === "ArrowDown") dy = step;
    else return;
    event.preventDefault();
    const next = box.map((p) => ({ x: p.x + dx, y: p.y + dy })) as BoundingBox;
    onChangeBox(selectedIndex, next);
  }

  const hasBoxMenu = Boolean(onDuplicateSelected || onBringSelectedToFront || onDeleteSelected);

  return (
    <div
      className="quad-editor"
      tabIndex={0}
      onKeyDown={handleKeyDown}
      onClick={() => setMenu(null)}
    >
      <img
        src={imageUrl}
        alt="Rendered preview"
        onLoad={(e) =>
          setNaturalSize([e.currentTarget.naturalWidth, e.currentTarget.naturalHeight])
        }
        className="quad-editor__image"
      />
      {naturalSize && (
        <svg
          ref={svgRef}
          className="quad-editor__overlay"
          viewBox={`0 0 ${naturalSize[0]} ${naturalSize[1]}`}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
        >
          {boxes.map((box, boxIndex) => {
            const active = boxIndex === selectedIndex;
            if (outlines === "none") return null;
            if (outlines === "selected" && !active) return null;
            return (
              <g
                key={boxIndex}
                className={
                  active ? "quad-editor__box" : "quad-editor__box quad-editor__box--dimmed"
                }
                onClick={() => onSelect(boxIndex)}
                onContextMenu={(event) => {
                  if (!hasBoxMenu) return;
                  event.preventDefault();
                  onSelect(boxIndex);
                  setMenu(menuAnchor(event.clientX, event.clientY, svgRef.current));
                }}
              >
                <polygon
                  points={box.map((p) => `${p.x},${p.y}`).join(" ")}
                  className="quad-editor__polygon"
                />
                {active &&
                  box.map((p, pointIndex) => (
                    <circle
                      key={pointIndex}
                      cx={p.x}
                      cy={p.y}
                      r={Math.max(naturalSize[0], naturalSize[1]) * 0.015}
                      className="quad-editor__handle"
                      onPointerDown={handlePointerDown(pointIndex)}
                    />
                  ))}
              </g>
            );
          })}
        </svg>
      )}

      {selectedLabel && <span className="quad-editor__readout">{selectedLabel}</span>}

      {onAddBox && (
        <button type="button" className="btn btn-primary quad-editor__add" onClick={onAddBox}>
          + Add box
        </button>
      )}

      {menu && (
        <div className="quad-editor__menu" ref={menuRef} role="menu">
          {onDuplicateSelected && (
            <button type="button" role="menuitem" onClick={onDuplicateSelected}>
              Duplicate
            </button>
          )}
          {onBringSelectedToFront && (
            <button type="button" role="menuitem" onClick={onBringSelectedToFront}>
              Bring to front
            </button>
          )}
          {onDeleteSelected && (
            <button
              type="button"
              role="menuitem"
              className="quad-editor__menu-danger"
              onClick={onDeleteSelected}
            >
              Delete ⌫
            </button>
          )}
        </div>
      )}
    </div>
  );
}
