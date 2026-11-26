import {
  type ReactNode,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import type { CanvasPoint, PhotoPoint, PhotoPx, ScreenPx } from "../pixels";
import type { BoundingBox, PhotoSpace } from "../types";
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
  space: PhotoSpace;
  boxes: BoundingBox[];
  selectedIndex: number;
  onSelect: (index: number) => void;
  onChangeBox: (index: number, box: BoundingBox) => void;
  onAddBox?: () => void;
  onDeleteSelected?: () => void;
  onDuplicateSelected?: () => void;
  onBringSelectedToFront?: () => void;
  /** `selected` hides the other boxes while one is edited; `none` hides all of
   * them, to judge the render. */
  outlines?: "all" | "selected" | "none";
  /** Per-box caption drawn under the box and edited by clicking it. */
  labels?: (string | undefined)[];
  onLabelChange?: (index: number, value: string) => void;
  labelPlaceholder?: string;
  labelSuggestions?: string[];
}

type Menu = CanvasPoint;

type Drag = { pointerId: number } & (
  | { kind: "corner"; pointIndex: number; start: BoundingBox }
  | { kind: "box"; boxIndex: number; origin: PhotoPoint; start: BoundingBox }
);

const DRAG_TARGETS = ".quad-editor__polygon, .quad-editor__handle, .quad-editor__grip";

/** On a phone, a finger that lands on a box or a corner keeps the whole touch.
 *
 * Chromium ignores `touch-action: none` on SVG shapes, so under the overlay's
 * `pan-y` a drag followed a few pixels and then scrolled. Cancelling the
 * touchstart is the one signal it honours, and needs a non-passive listener,
 * which React's are not. A second finger is held too, so it cannot pinch the page. */
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

function useGripRadius(
  svg: SVGSVGElement | null,
  imageWidth: PhotoPx,
  dotRadius: PhotoPx,
): PhotoPx {
  const [overlayWidth, setOverlayWidth] = useState<ScreenPx>(0);
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

function menuAnchor(clientX: ScreenPx, clientY: ScreenPx, svg: SVGSVGElement | null): Menu {
  const host = svg?.getBoundingClientRect();
  return { x: clientX - (host?.left ?? 0), y: clientY - (host?.top ?? 0) };
}

/** The nearest ancestor that clips its overflow, or the viewport. Not the
 * canvas: `.app__preview` clips and is often the shorter of the two. */
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
 * Measured, in a layout effect before paint: the menu is ~90px tall and the
 * preview pane can be barely more. */
function positionMenu(el: HTMLElement, menu: Menu): void {
  Object.assign(el.style, { left: `${menu.x}px`, top: `${menu.y}px` });
  const rect = el.getBoundingClientRect();
  const host = { x: rect.left - menu.x, y: rect.top - menu.y };
  const placed = menuPlacement(menu, host, rect, clipRect(el));
  Object.assign(el.style, { left: `${placed.x}px`, top: `${placed.y}px` });
}

/** A phone has no right button, and a long press is the browser's own. */
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

  function toImageSpace(clientX: ScreenPx, clientY: ScreenPx): PhotoPoint | null {
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
  const dotRadius: PhotoPx = Math.max(space[0], space[1]) * 0.015;
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
    // Shift is read per move, not per press, so it can be pressed mid-gesture.
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
  // Outside the canvas, which the phone overlay covers entirely.
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
