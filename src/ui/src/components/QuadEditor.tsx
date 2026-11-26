import {
  type ReactNode,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import type { BoundingBox, Point } from "../types";
import { useLatest } from "../hooks/useLatest";
import { useIsPhone } from "../phone/usePhone";
import {
  cornerDragged,
  gripCentre,
  gripRadius,
  labelAnchor,
  menuPlacement,
  moved,
  nudged,
} from "./quadGeometry";

interface Props {
  overlay?: ReactNode;
  interactive?: boolean;
  imageUrl: string;
  /** The template photo's **true** `[width, height]`, from the API, not
   * `naturalWidth`: the editor shows a downscale (docs/architecture.md). */
  space: [number, number];
  boxes: BoundingBox[];
  selectedIndex: number;
  onSelect: (index: number) => void;
  onChangeBox: (index: number, box: BoundingBox) => void;
  onAddBox?: () => void;
  onDeleteSelected?: () => void;
  onDuplicateSelected?: () => void;
  onBringSelectedToFront?: () => void;
  /** How much box chrome to draw. Three states rather than a boolean because
   * 2a's two toggles mean different things: a chart's "Show all design boxes"
   * hides the *other* boxes while you keep working on one ("selected"), and a
   * colour set's "Show design box" hides everything so you can judge
   * the render clean ("none"). */
  outlines?: "all" | "selected" | "none";
  /** Per-box caption drawn under the box and edited by clicking it. */
  labels?: (string | undefined)[];
  onLabelChange?: (index: number, value: string) => void;
  labelPlaceholder?: string;
  labelSuggestions?: string[];
}

interface Menu {
  /** Where the menu opens, in `.quad-editor` px. */
  x: number;
  y: number;
}

type Drag = { pointerId: number } & (
  | { kind: "corner"; pointIndex: number; start: BoundingBox }
  | { kind: "box"; boxIndex: number; origin: Point; start: BoundingBox }
);

const DRAG_TARGETS = ".quad-editor__polygon, .quad-editor__handle, .quad-editor__grip";

/** On a phone, a finger that lands on a box or a corner keeps the whole touch.
 *
 * The overlay lets a finger elsewhere on the photo scroll the page
 * (`touch-action: pan-y` in phone/calibrator.css), and Chromium ignores the
 * `touch-action: none` the box and its corners ask for, since they are SVG
 * shapes: the drag followed for a few pixels, then the browser cancelled it
 * and scrolled instead. Cancelling the touchstart is the one signal it
 * honours. Not passive, so React's own touch listeners cannot do this. A
 * second finger landing mid-drag is held too, so it cannot pinch the page
 * under the box being dragged. */
function useTouchClaim(
  svg: SVGSVGElement | null,
  enabled: boolean,
  dragging: { readonly current: boolean },
): void {
  useEffect(() => {
    if (!svg || !enabled) return;
    const claim = (event: TouchEvent) => {
      const target = event.target as Element | null;
      if (dragging.current || target?.closest?.(DRAG_TARGETS)) event.preventDefault();
    };
    svg.addEventListener("touchstart", claim, { passive: false });
    return () => svg.removeEventListener("touchstart", claim);
  }, [svg, enabled, dragging]);
}

function useGripRadius(svg: SVGSVGElement | null, imageWidth: number, dotRadius: number): number {
  const [overlayWidth, setOverlayWidth] = useState(0);
  useLayoutEffect(() => {
    if (!svg) return;
    const measure = () => setOverlayWidth(svg.getBoundingClientRect().width);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(svg);
    return () => observer.disconnect();
  }, [svg]);
  return gripRadius(overlayWidth, imageWidth, dotRadius);
}

function isTypingInField(event: React.KeyboardEvent): boolean {
  return (event.target as Element).closest("input, textarea") !== null;
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
  const host = { x: rect.left - menu.x, y: rect.top - menu.y };
  const placed = menuPlacement(menu, host, rect, clipRect(el));
  Object.assign(el.style, { left: `${placed.x}px`, top: `${placed.y}px` });
}

/** The right-click menu's actions as a row under the photo, on a phone: a
 * finger has no right button, and a long press is the browser's own. */
function BoxActions({
  onAdd,
  onDuplicate,
  onBringToFront,
  onDelete,
}: {
  onAdd: (() => void) | undefined;
  onDuplicate: (() => void) | undefined;
  onBringToFront: (() => void) | undefined;
  onDelete: (() => void) | undefined;
}) {
  return (
    <div className="quad-editor__phone-actions" role="toolbar" aria-label="Boxes">
      {onAdd && (
        <button type="button" className="btn btn-primary" onClick={onAdd}>
          + Add box
        </button>
      )}
      {onDuplicate && (
        <button type="button" className="btn btn-secondary" onClick={onDuplicate}>
          Duplicate
        </button>
      )}
      {onBringToFront && (
        <button type="button" className="btn btn-secondary" onClick={onBringToFront}>
          Bring to front
        </button>
      )}
      {onDelete && (
        <button
          type="button"
          className="btn btn-secondary quad-editor__phone-danger"
          onClick={onDelete}
        >
          Delete
        </button>
      )}
    </div>
  );
}

/** The SVG's viewBox is the photo's true size, so screen-to-image mapping
 * goes through the SVG's own CTM, whatever the browser's display scale. */
export function QuadEditor({
  overlay,
  interactive = true,
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
  const svgRef = useRef<SVGSVGElement | null>(null);
  // The overlay mounts only once the image has loaded, so the phone's touch
  // claim and grip measuring need to hear when it does.
  const [svgNode, setSvgNode] = useState<SVGSVGElement | null>(null);
  const attachSvg = useCallback((node: SVGSVGElement | null) => {
    svgRef.current = node;
    setSvgNode(node);
  }, []);
  const phone = useIsPhone();
  const [imageLaidOut, setImageLaidOut] = useState(false);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [menu, setMenu] = useState<Menu | null>(null);
  const [editingLabel, setEditingLabel] = useState<number | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const suggestionsId = useId();

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

  const dragging = useLatest(drag !== null);
  useTouchClaim(svgNode, phone && interactive, dragging);
  const dotRadius = Math.max(space[0], space[1]) * 0.015;
  const gripR = useGripRadius(phone ? svgNode : null, space[0], dotRadius);

  function handleCornerPointerDown(pointIndex: number) {
    return (event: React.PointerEvent<SVGCircleElement>) => {
      const start = boxes[selectedIndex];
      if (!start || !interactive || drag) return;
      event.currentTarget.setPointerCapture(event.pointerId);
      setDrag({ kind: "corner", pointIndex, start, pointerId: event.pointerId });
    };
  }

  function handleBoxPointerDown(boxIndex: number) {
    return (event: React.PointerEvent<SVGPolygonElement>) => {
      if (event.button !== 0 || !interactive || drag) return;
      const origin = toImageSpace(event.clientX, event.clientY);
      const start = boxes[boxIndex];
      if (!origin || !start) return;
      event.currentTarget.setPointerCapture(event.pointerId);
      onSelect(boxIndex);
      setDrag({ kind: "box", boxIndex, origin, start, pointerId: event.pointerId });
    };
  }

  function handlePointerMove(event: React.PointerEvent<SVGSVGElement>) {
    if (!drag || !interactive || event.pointerId !== drag.pointerId) return;
    const point = toImageSpace(event.clientX, event.clientY);
    if (!point) return;
    if (drag.kind === "box") {
      onChangeBox(drag.boxIndex, moved(drag.start, drag.origin, point));
      return;
    }
    // The modifier is read per move, not per press, so shift can be taken
    // and released mid-gesture -- reach for a corner, discover you wanted the
    // whole box bigger, hold shift.
    onChangeBox(
      selectedIndex,
      cornerDragged(drag.start, drag.pointIndex, point, {
        shift: event.shiftKey,
        alt: event.altKey,
      }),
    );
  }

  function handlePointerEnd(event: React.PointerEvent<SVGSVGElement>) {
    if (drag && event.pointerId !== drag.pointerId) return;
    setDrag(null);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (!interactive) return;
    if (isTypingInField(event)) return;
    if ((event.key === "Delete" || event.key === "Backspace") && onDeleteSelected) {
      event.preventDefault();
      onDeleteSelected();
      return;
    }
    const box = boxes[selectedIndex];
    if (!box) return;
    const next = nudged(box, event.key, event.shiftKey);
    if (!next) return;
    event.preventDefault();
    onChangeBox(selectedIndex, next);
  }

  const hasBoxMenu = Boolean(onDuplicateSelected || onBringSelectedToFront || onDeleteSelected);

  const chromeVisible = (index: number): boolean =>
    outlines === "all" || (outlines === "selected" && index === selectedIndex);

  const canvas = (
    <div
      className="quad-editor"
      tabIndex={0}
      onKeyDown={handleKeyDown}
      onClick={() => setMenu(null)}
    >
      <img
        src={imageUrl}
        alt="Rendered preview"
        onLoad={() => setImageLaidOut(true)}
        className="quad-editor__image"
      />
      {imageLaidOut && (
        <svg
          ref={attachSvg}
          className="quad-editor__overlay"
          viewBox={`0 0 ${space[0]} ${space[1]}`}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerEnd}
          onPointerCancel={handlePointerEnd}
          onLostPointerCapture={handlePointerEnd}
        >
          {overlay}
          {boxes.map((box, boxIndex) => {
            const active = boxIndex === selectedIndex;
            if (!chromeVisible(boxIndex)) return null;
            return (
              <g
                key={boxIndex}
                className={
                  active ? "quad-editor__box" : "quad-editor__box quad-editor__box--dimmed"
                }
                onClick={() => {
                  if (interactive) onSelect(boxIndex);
                }}
                onContextMenu={(event) => {
                  if (!hasBoxMenu || !interactive) return;
                  event.preventDefault();
                  onSelect(boxIndex);
                  setMenu(menuAnchor(event.clientX, event.clientY, svgRef.current));
                }}
              >
                <polygon
                  points={box.map((p) => `${p.x},${p.y}`).join(" ")}
                  className="quad-editor__polygon"
                  pointerEvents={interactive ? undefined : "none"}
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
                      pointerEvents={interactive ? undefined : "none"}
                      onPointerDown={handleCornerPointerDown(pointIndex)}
                    />
                  ))}
                {active &&
                  phone &&
                  interactive &&
                  box.map((p, pointIndex) => {
                    const at = gripCentre(p, gripR, space);
                    return (
                      <circle
                        key={pointIndex}
                        cx={at.x}
                        cy={at.y}
                        r={gripR}
                        className="quad-editor__grip"
                        data-corner={pointIndex}
                        onPointerDown={handleCornerPointerDown(pointIndex)}
                      />
                    );
                  })}
              </g>
            );
          })}
        </svg>
      )}

      {imageLaidOut && labels && (
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
                  autoFocus
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
                  if (onLabelChange && interactive) setEditingLabel(boxIndex);
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

      {onAddBox && interactive && !phone && (
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
  // On a phone the box actions sit under the photo, outside the canvas: the
  // overlay stretches over everything inside it.
  if (!phone || !interactive || !(onAddBox || hasBoxMenu)) return canvas;
  return (
    <>
      {canvas}
      <BoxActions
        onAdd={onAddBox}
        onDuplicate={boxes[selectedIndex] ? onDuplicateSelected : undefined}
        onBringToFront={boxes[selectedIndex] ? onBringSelectedToFront : undefined}
        onDelete={boxes[selectedIndex] ? onDeleteSelected : undefined}
      />
    </>
  );
}
