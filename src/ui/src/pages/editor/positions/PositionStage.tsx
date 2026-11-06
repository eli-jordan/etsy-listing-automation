import { type KeyboardEvent, type PointerEvent, useLayoutEffect, useRef, useState } from "react";
import { type Point, type Quad, compose, homography, toPhoto } from "./pose";
import type { Gesture, Layer, Positioning } from "./usePositioning";

/**
 * The preview stage in Position mode: the saved composite, the handles for
 * the selected box, the other placements dimmed, the template's box as a
 * ghost, and -- while a gesture is unsaved -- the artwork flat on the draft
 * box. Copied from the prototype's `PositionStage`
 * (`design/scenes/template-positions/_PositionStage.tsx`), except that every
 * box is the template's quad under the pose through its homography, so
 * handles sit on the mapped corners rather than an axis-aligned rectangle.
 */

interface Props {
  positioning: Positioning;
  /** The saved composite. */
  picture: string;
  title: string;
  /** The listing's artwork, for the draft overlay; `null` draws none. */
  artwork: string | null;
}

/** Handle half-size and tilt-stem length, in screen pixels. */
const HANDLE = 5;
const STEM = 22;

const points = (quad: readonly Point[]) => quad.map((p) => `${p.x},${p.y}`).join(" ");

function safeCompose(layer: Layer): Quad {
  try {
    return compose(layer.box, layer.pose);
  } catch {
    return layer.box;
  }
}

/** CSS `matrix3d` taking a `w` x `h` element onto `quad` (photo pixels). */
function warp(quad: Quad, w: number, h: number): string {
  const [a, b, c, d, e, f, g, i, j] = homography(quad);
  const m = [a / w, d / w, 0, g / w, b / h, e / h, 0, i / h, 0, 0, 1, 0, c, f, 0, j];
  return `matrix3d(${m.join(",")})`;
}

/** The tilt handle: above the top edge's middle, away from the box's centre. */
function stemOf(layer: Layer, corners: Quad, k: number) {
  const top = { x: (corners[0].x + corners[1].x) / 2, y: (corners[0].y + corners[1].y) / 2 };
  let centre = { x: top.x, y: top.y + 1 };
  try {
    const unit = { x: 0.5 + layer.pose.offsetX, y: 0.5 + layer.pose.offsetY };
    centre = toPhoto(layer.box, unit);
  } catch {
    // Keep the straight-up fallback.
  }
  const dx = top.x - centre.x;
  const dy = top.y - centre.y;
  const length = Math.hypot(dx, dy) || 1;
  return { top, end: { x: top.x + (dx / length) * STEM * k, y: top.y + (dy / length) * STEM * k } };
}

export function PositionStage({ positioning, picture, title, artwork }: Props) {
  const { size, layers, selected } = positioning;
  const svg = useRef<SVGSVGElement>(null);
  /** Photo pixels per screen pixel, so handles keep their screen size. */
  const [k, setK] = useState(size.w / 480);

  useLayoutEffect(() => {
    const measure = () => {
      const rect = svg.current?.getBoundingClientRect();
      if (rect && rect.width > 0 && rect.height > 0) {
        setK(1 / Math.min(rect.width / size.w, rect.height / size.h));
      }
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [size.w, size.h]);

  /** Client to photo pixels, through `preserveAspectRatio`'s default meet. */
  function photoPoint(event: PointerEvent): Point {
    const rect = svg.current?.getBoundingClientRect();
    if (!rect) return { x: 0, y: 0 };
    const scale = Math.min(rect.width / size.w, rect.height / size.h);
    const left = rect.left + (rect.width - size.w * scale) / 2;
    const top = rect.top + (rect.height - size.h * scale) / 2;
    return { x: (event.clientX - left) / scale, y: (event.clientY - top) / scale };
  }

  function start(event: PointerEvent, gesture: Gesture, id: string) {
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    positioning.begin(gesture, id, photoPoint(event));
  }

  function key(event: KeyboardEvent) {
    if (positioning.nudge(event.key, event.shiftKey)) event.preventDefault();
  }

  const active = layers.find((l) => l.id === selected);

  return (
    <svg
      ref={svg}
      className="tp-stage"
      viewBox={`0 0 ${size.w} ${size.h}`}
      onPointerMove={(event) => positioning.move(photoPoint(event))}
      onPointerUp={positioning.end}
      onPointerCancel={positioning.end}
      role="group"
      aria-label={`${title} — position`}
    >
      <image
        href={picture}
        width={size.w}
        height={size.h}
        aria-label={title}
        onLoad={() => positioning.loaded(picture)}
        onError={positioning.recheck}
      />
      {positioning.overlay && active !== undefined && artwork !== null && (
        <Overlay layer={active} artwork={artwork} size={size} />
      )}
      {positioning.ghost && active !== undefined && (
        <>
          <polygon className="tp-halo" points={points(active.box)} />
          <polygon className="tp-ghost" points={points(active.box)} />
        </>
      )}
      {layers.map((layer) =>
        layer.id === selected ? (
          <Selected key={layer.id} layer={layer} k={k} onStart={start} onKey={key} />
        ) : (
          <Other key={layer.id} layer={layer} k={k} onSelect={positioning.select} />
        ),
      )}
    </svg>
  );
}

function Overlay({
  layer,
  artwork,
  size,
}: {
  layer: Layer;
  artwork: string;
  size: { w: number; h: number };
}) {
  const corners = safeCompose(layer);
  // The element's own aspect is the template box's, so `contain` keeps the
  // artwork's proportions roughly as the render fits it.
  const w = Math.hypot(layer.box[1].x - layer.box[0].x, layer.box[1].y - layer.box[0].y) || 1;
  const h = Math.hypot(layer.box[3].x - layer.box[0].x, layer.box[3].y - layer.box[0].y) || 1;
  return (
    <foreignObject x={0} y={0} width={size.w} height={size.h} className="tp-overlay">
      <div
        style={{
          width: w,
          height: h,
          transformOrigin: "0 0",
          transform: warp(corners, w, h),
        }}
      >
        <img src={artwork} alt="" />
      </div>
    </foreignObject>
  );
}

function Selected({
  layer,
  k,
  onStart,
  onKey,
}: {
  layer: Layer;
  k: number;
  onStart: (event: PointerEvent, gesture: Gesture, id: string) => void;
  onKey: (event: KeyboardEvent) => void;
}) {
  const corners = safeCompose(layer);
  // A refused box is drawn where it is stored, not where the fit would put it.
  const outline = layer.invalid !== null && layer.stored !== null ? layer.stored : corners;
  const stem = stemOf(layer, corners, k);
  const half = HANDLE * k;
  return (
    <g>
      <polygon
        className={
          layer.invalid === null ? "tp-box tp-box--on" : "tp-box tp-box--on tp-box--invalid"
        }
        points={points(outline)}
        role="button"
        tabIndex={0}
        aria-label={`${layer.placement ?? "Design"} position — drag to move, arrow keys to nudge`}
        onPointerDown={(event) => onStart(event, "move", layer.id)}
        onKeyDown={onKey}
      />
      <line className="tp-stem" x1={stem.top.x} y1={stem.top.y} x2={stem.end.x} y2={stem.end.y} />
      <circle
        className="tp-handle tp-handle--rotate"
        cx={stem.end.x}
        cy={stem.end.y}
        r={half * 1.1}
        aria-label="Drag to tilt"
        onPointerDown={(event) => onStart(event, "rotate", layer.id)}
      >
        <title>Drag to tilt</title>
      </circle>
      {corners.map((corner, index) => (
        <rect
          key={index}
          className="tp-handle tp-handle--scale"
          x={corner.x - half}
          y={corner.y - half}
          width={half * 2}
          height={half * 2}
          aria-label="Drag to resize"
          onPointerDown={(event) => onStart(event, "scale", layer.id)}
        >
          <title>Drag to resize</title>
        </rect>
      ))}
    </g>
  );
}

function Other({
  layer,
  k,
  onSelect,
}: {
  layer: Layer;
  k: number;
  onSelect: (id: string) => void;
}) {
  const corners = safeCompose(layer);
  const label = layer.placement ?? layer.id;
  return (
    <g>
      <polygon className="tp-halo" points={points(corners)} />
      <polygon
        className="tp-box tp-box--off"
        points={points(corners)}
        role="button"
        tabIndex={0}
        aria-label={`Select ${label}`}
        onPointerDown={(event) => {
          event.stopPropagation();
          onSelect(layer.id);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onSelect(layer.id);
          }
        }}
      />
      <text className="tp-tag" x={corners[0].x + 4 * k} y={corners[0].y - 6 * k} fontSize={13 * k}>
        {label}
      </text>
    </g>
  );
}
