import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { BoundingBox, Point } from "../types";

const NUDGE_PX = 1;
const NUDGE_PX_FAST = 8;

interface Props {
  imageUrl: string;
  /** The template photo's **true** `[width, height]`, from the API.
   *
   * Not measured off `imageUrl`. The editor renders at a downscale, so the
   * image on screen is smaller than the photo -- but `template.yaml` stores
   * boxes at the photo's true size, and so does everything in this component.
   * Reading `naturalWidth` instead (which is what this used to do) would put
   * the overlay in the *preview's* space and silently save every box a few
   * times too small.
   *
   * Nothing breaks visually if it is a little wrong, which is exactly why it
   * is a required prop rather than an optional override: the failure is in the
   * saved file, not on the screen. */
  space: [number, number];
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
  /** Per-box caption drawn under the box and edited by clicking it.
   *
   * This is where a `multiple`-kind placement's colour lives now. It used to
   * be a field in a side panel, which meant the one thing a box *cannot* show
   * you -- which garment it is -- was the one thing you had to look away from
   * the photo to read. A caption on the box says it in place.
   *
   * Drawn under exactly the boxes whose outline is drawn, so `outlines`
   * governs both: hiding the chrome to judge a render hides the captions too. */
  labels?: (string | undefined)[];
  onLabelChange?: (index: number, value: string) => void;
  labelPlaceholder?: string;
  /** Offered in the label input's datalist. Suggestions, not a closed list. */
  labelSuggestions?: string[];
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
 *
 * A box moves as a whole in two ways -- dragging its interior, or the arrow
 * keys -- and deforms only by its corner handles. Both apply to every kind:
 * getting a box to the right *place* is the common move, and before this the
 * only way to do it was to drag four corners the same distance by eye.
 *
 * A corner handle does three things, chosen by modifier:
 *
 * | gesture | effect |
 * |---|---|
 * | drag | moves that corner alone -- the quad deforms, which is what makes it a *perspective* placement and not a rectangle |
 * | shift-drag | scales the whole box about the opposite corner, shape preserved |
 * | alt-drag | scales it about its own centre |
 *
 * Nothing on the canvas announces that, and nothing labels the selected box
 * either. Both used to sit in a pill over the photo, and both were in the way
 * of the one thing this view exists for -- looking at the render. The selected
 * box is the one wearing handles, which is the answer already.
 *
 * Free-corner is the unmodified gesture because it is the one only this
 * control can do. But "same shape, bigger" is the far more common wish -- a
 * print that is placed right and simply too small -- and doing it by hand
 * means dragging four corners by four different amounts and re-checking the
 * skew after each. Scaling keeps the corners' offsets from the anchor exactly
 * proportional, so an already-skewed quad stays exactly as skewed.
 */

interface Menu {
  /** Where the menu opens, in `.quad-editor` px. */
  x: number;
  y: number;
}

/** What a pointer is currently doing: working one corner of the selected box,
 * or sliding a whole box (which need not be the selected one -- pressing on a
 * dimmed box selects and drags it in one gesture).
 *
 * Both carry the box as it was when the gesture started. A corner drag needs
 * it because scaling is defined against the *original* offsets: derived from
 * the live box instead, every mouse move would compound on the last one and
 * the box would race away from the pointer. */
type Drag =
  | { kind: "corner"; pointIndex: number; start: BoundingBox }
  | { kind: "box"; boxIndex: number; origin: Point; start: BoundingBox };

/** How far a box may be shrunk in one gesture. Not zero: at zero the box
 * collapses to a point, and a point has no corners left to drag it back
 * out by. */
const MIN_SCALE = 0.05;

function centre(box: BoundingBox): Point {
  return {
    x: box.reduce((sum, p) => sum + p.x, 0) / box.length,
    y: box.reduce((sum, p) => sum + p.y, 0) / box.length,
  };
}

/**
 * `start`, scaled about `anchor` so that its `pointIndex` corner sits as close
 * to `pointer` as a shape-preserving scale allows.
 *
 * The factor is the pointer's projection onto the anchor-to-corner vector, so
 * dragging along that diagonal tracks the cursor exactly and dragging across
 * it does nothing -- which is what "same shape, bigger or smaller" means. Every
 * corner is then moved by the same factor, so all four angles, and therefore
 * any perspective skew the box already had, are preserved exactly.
 */
function scaledAbout(
  start: BoundingBox,
  pointIndex: number,
  anchor: Point,
  pointer: Point,
): BoundingBox {
  const corner = start[pointIndex];
  if (!corner) return start;
  const vx = corner.x - anchor.x;
  const vy = corner.y - anchor.y;
  const lengthSquared = vx * vx + vy * vy;
  // A corner sitting on its own anchor has no direction to scale along --
  // only reachable from a degenerate box, but dividing by it would produce
  // NaN coordinates and a box that vanishes.
  if (lengthSquared === 0) return start;
  const factor = Math.max(
    MIN_SCALE,
    ((pointer.x - anchor.x) * vx + (pointer.y - anchor.y) * vy) / lengthSquared,
  );
  return start.map((p) => ({
    x: anchor.x + (p.x - anchor.x) * factor,
    y: anchor.y + (p.y - anchor.y) * factor,
  })) as BoundingBox;
}

function menuAnchor(clientX: number, clientY: number, svg: SVGSVGElement | null): Menu {
  const host = svg?.getBoundingClientRect();
  return { x: clientX - (host?.left ?? 0), y: clientY - (host?.top ?? 0) };
}

/** Where a box's caption hangs: centred under its lowest edge. */
function labelAnchor(box: BoundingBox): Point {
  const xs = box.map((p) => p.x);
  const ys = box.map((p) => p.y);
  return { x: (Math.min(...xs) + Math.max(...xs)) / 2, y: Math.max(...ys) };
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
  space,
  boxes,
  selectedIndex,
  onSelect,
  onChangeBox,
  onAddBox,
  onDeleteSelected,
  onDuplicateSelected,
  onBringSelectedToFront,
  outlines = "all",
  labels,
  onLabelChange,
  labelPlaceholder,
  labelSuggestions,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  // Purely a gate on drawing the overlay: the SVG is stretched over the image,
  // so it has no size of its own until the image has laid out. Deliberately
  // not a measurement -- `space` is where coordinates come from.
  const [loaded, setLoaded] = useState(false);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [menu, setMenu] = useState<Menu | null>(null);
  const [editingLabel, setEditingLabel] = useState<number | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const labelInputRef = useRef<HTMLInputElement>(null);
  const suggestionsId = useId();

  useLayoutEffect(() => {
    if (menu && menuRef.current) positionMenu(menuRef.current, menu);
  }, [menu]);

  // A caption only becomes an input when it is clicked, so the caret has to be
  // put there afterwards -- otherwise the click that opened the field leaves
  // it unfocused and the next keystroke nudges the box instead.
  useEffect(() => {
    if (editingLabel !== null) labelInputRef.current?.focus();
  }, [editingLabel]);

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

  function handleCornerPointerDown(pointIndex: number) {
    return (event: React.PointerEvent<SVGCircleElement>) => {
      const start = boxes[selectedIndex];
      if (!start) return;
      event.currentTarget.setPointerCapture(event.pointerId);
      setDrag({ kind: "corner", pointIndex, start });
    };
  }

  /** Pressing inside a box selects it and starts sliding it. The whole box
   * moves; the corners keep their offsets, so a skewed quad stays skewed. */
  function handleBoxPointerDown(boxIndex: number) {
    return (event: React.PointerEvent<SVGPolygonElement>) => {
      if (event.button !== 0) return;
      const origin = toImageSpace(event.clientX, event.clientY);
      const start = boxes[boxIndex];
      if (!origin || !start) return;
      event.currentTarget.setPointerCapture(event.pointerId);
      onSelect(boxIndex);
      setDrag({ kind: "box", boxIndex, origin, start });
    };
  }

  function handlePointerMove(event: React.PointerEvent<SVGSVGElement>) {
    if (!drag) return;
    const point = toImageSpace(event.clientX, event.clientY);
    if (!point) return;
    if (drag.kind === "box") {
      const dx = point.x - drag.origin.x;
      const dy = point.y - drag.origin.y;
      onChangeBox(
        drag.boxIndex,
        drag.start.map((p) => ({ x: p.x + dx, y: p.y + dy })) as BoundingBox,
      );
      return;
    }
    // The modifier is read per move, not per press, so shift can be taken
    // and released mid-gesture -- reach for a corner, discover you wanted the
    // whole box bigger, hold shift.
    const { start, pointIndex } = drag;
    const opposite = start[(pointIndex + 2) % start.length];
    if (event.shiftKey && opposite) {
      onChangeBox(selectedIndex, scaledAbout(start, pointIndex, opposite, point));
      return;
    }
    if (event.altKey) {
      onChangeBox(selectedIndex, scaledAbout(start, pointIndex, centre(start), point));
      return;
    }
    onChangeBox(selectedIndex, start.map((p, i) => (i === pointIndex ? point : p)) as BoundingBox);
  }

  function handlePointerUp() {
    setDrag(null);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    // The caption editor lives inside the canvas, so its arrows, Backspace and
    // Delete would otherwise reach the box while you are typing a colour name.
    if ((event.target as Element).closest("input, textarea")) return;
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

  /** One rule for both the outline and the caption: chrome is drawn for a box
   * when all outlines are on, or when it is the selected one. */
  const chromeVisible = (index: number): boolean =>
    outlines === "all" || (outlines === "selected" && index === selectedIndex);

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
        onLoad={() => setLoaded(true)}
        className="quad-editor__image"
      />
      {loaded && (
        <svg
          ref={svgRef}
          className="quad-editor__overlay"
          viewBox={`0 0 ${space[0]} ${space[1]}`}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
        >
          {boxes.map((box, boxIndex) => {
            const active = boxIndex === selectedIndex;
            if (!chromeVisible(boxIndex)) return null;
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
                  onPointerDown={handleBoxPointerDown(boxIndex)}
                />
                {active &&
                  box.map((p, pointIndex) => (
                    <circle
                      key={pointIndex}
                      cx={p.x}
                      cy={p.y}
                      r={Math.max(space[0], space[1]) * 0.015}
                      className="quad-editor__handle"
                      onPointerDown={handleCornerPointerDown(pointIndex)}
                    />
                  ))}
              </g>
            );
          })}
        </svg>
      )}

      {loaded && labels && (
        <div className="quad-editor__labels">
          {boxes.map((box, boxIndex) => {
            if (!chromeVisible(boxIndex)) return null;
            const anchor = labelAnchor(box);
            const style = {
              left: `${(anchor.x / space[0]) * 100}%`,
              top: `${(anchor.y / space[1]) * 100}%`,
            };
            const text = labels[boxIndex] ?? "";
            if (editingLabel === boxIndex && onLabelChange) {
              return (
                <input
                  key={boxIndex}
                  ref={labelInputRef}
                  className="quad-editor__label quad-editor__label--editing"
                  style={style}
                  value={text}
                  aria-label={`Colour for box ${boxIndex + 1}`}
                  placeholder={labelPlaceholder}
                  list={suggestionsId}
                  onChange={(event) => onLabelChange(boxIndex, event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === "Escape") setEditingLabel(null);
                  }}
                  onBlur={() => setEditingLabel(null)}
                />
              );
            }
            return (
              <button
                key={boxIndex}
                type="button"
                style={style}
                className={[
                  "quad-editor__label",
                  text ? "" : "quad-editor__label--empty",
                  boxIndex === selectedIndex ? "quad-editor__label--active" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                title={onLabelChange ? "Click to edit" : undefined}
                onClick={() => {
                  onSelect(boxIndex);
                  if (onLabelChange) setEditingLabel(boxIndex);
                }}
              >
                {text || labelPlaceholder || "unnamed"}
              </button>
            );
          })}
          {labelSuggestions && labelSuggestions.length > 0 && (
            <datalist id={suggestionsId}>
              {labelSuggestions.map((suggestion) => (
                <option key={suggestion} value={suggestion} />
              ))}
            </datalist>
          )}
        </div>
      )}

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
