import { useRef, useState } from "react";
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
  /** When false, the unselected boxes' outlines are hidden -- 2a's "show
   * placement outline" toggle, for judging the render without chrome. */
  showOutlines?: boolean;
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
  showOutlines = true,
  selectedLabel,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [naturalSize, setNaturalSize] = useState<[number, number] | null>(null);
  const [dragPointIndex, setDragPointIndex] = useState<number | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);

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
            // Hiding the *unselected* outlines only: the selected box keeps
            // its handles, because the toggle is for judging the render, not
            // for giving up the ability to fix it.
            if (!active && !showOutlines) return null;
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
                  const host = event.currentTarget.ownerSVGElement?.getBoundingClientRect();
                  setMenu({
                    x: event.clientX - (host?.left ?? 0),
                    y: event.clientY - (host?.top ?? 0),
                  });
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
        <div className="quad-editor__menu" style={{ left: menu.x, top: menu.y }} role="menu">
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
