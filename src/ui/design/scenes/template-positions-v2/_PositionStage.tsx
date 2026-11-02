import { useRef, type KeyboardEvent, type PointerEvent } from "react";
import {
  centreOf,
  clampPose,
  isIdentity,
  poseTransform,
  type Bounds,
  type Pose,
  type Rect,
} from "./_geometry";

export interface Layer {
  id: string;
  box: Rect;
  pose: Pose;
  label?: string;
}

interface Props {
  photo: string;
  size: { w: number; h: number };
  artwork: string;
  layers: Layer[];
  /** Positioning this layer; the others render dimmed and click-to-select. */
  editing?: string | null;
  limits: Bounds;
  onChange?: (id: string, pose: Pose) => void;
  onSelect?: (id: string) => void;
  /** Draw the template's own box behind the edited one. */
  ghost?: boolean;
  /** Red outline: this layer's stored position fails plan. */
  invalid?: string | null;
  /** The edited box has stopped at a limit: its handles turn amber. */
  atLimit?: boolean;
}

type Drag =
  | { kind: "move"; id: string; start: { x: number; y: number }; pose: Pose }
  | { kind: "scale"; id: string; pose: Pose }
  | { kind: "rotate"; id: string; pose: Pose };

/**
 * The preview stage in Position mode. The composite is faked with the
 * artwork multiplied onto the photo; the real pane asks the preview route
 * with the draft position. Handles stop at the limits instead of letting
 * the seller drag into something `plan` would refuse.
 */
export function PositionStage({ photo, size, artwork, layers, editing, limits, onChange, onSelect, ghost, invalid, atLimit }: Props) {
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<Drag | null>(null);

  const toPhoto = (e: PointerEvent) => {
    const m = svg.current?.getScreenCTM();
    if (!m) return { x: 0, y: 0 };
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(m.inverse());
    return { x: p.x, y: p.y };
  };

  const layerById = (id: string) => layers.find((l) => l.id === id)!;

  function move(e: PointerEvent) {
    const d = drag.current;
    if (!d || !onChange) return;
    const { box } = layerById(d.id);
    const p = toPhoto(e);
    if (d.kind === "move") {
      onChange(d.id, clampPose({ ...d.pose, dx: d.pose.dx + (p.x - d.start.x) / box.w, dy: d.pose.dy + (p.y - d.start.y) / box.h }, limits));
    } else {
      const c = centreOf(box, d.pose);
      if (d.kind === "scale") {
        const half = Math.hypot(box.w, box.h) / 2;
        onChange(d.id, clampPose({ ...d.pose, scale: Math.hypot(p.x - c.x, p.y - c.y) / half }, limits));
      } else {
        const a = (Math.atan2(p.y - c.y, p.x - c.x) * 180) / Math.PI + 90;
        onChange(d.id, clampPose({ ...d.pose, rotation: Math.round(a) }, limits));
      }
    }
  }

  function start(e: PointerEvent, next: Drag) {
    e.stopPropagation();
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    drag.current = next;
  }

  function nudge(e: KeyboardEvent, l: Layer) {
    if (!onChange) return;
    const step = e.shiftKey ? 0.05 : 0.01;
    const k: Record<string, Partial<Pose>> = {
      ArrowLeft: { dx: l.pose.dx - step },
      ArrowRight: { dx: l.pose.dx + step },
      ArrowUp: { dy: l.pose.dy - step },
      ArrowDown: { dy: l.pose.dy + step },
    };
    if (!k[e.key]) return;
    e.preventDefault();
    onChange(l.id, clampPose({ ...l.pose, ...k[e.key] }, limits));
  }

  return (
    <svg
      ref={svg}
      className="tp-stage"
      viewBox={`0 0 ${size.w} ${size.h}`}
      onPointerMove={move}
      onPointerUp={() => (drag.current = null)}
      onPointerCancel={() => (drag.current = null)}
      data-at-limit={atLimit ? "" : undefined}
      role="img"
      aria-label="Mockup preview"
    >
      <image href={photo} width={size.w} height={size.h} />

      {layers.map((l) => (
        <g key={`art-${l.id}`} transform={poseTransform(l.box, l.pose)} className="tp-print">
          <image href={artwork} width={l.box.w} height={l.box.h} preserveAspectRatio="xMidYMid meet" />
        </g>
      ))}

      {editing != null &&
        layers.map((l) => {
          const on = l.id === editing;
          const s = l.pose.scale;
          const halfHandle = 5 / s;
          const stroke = 1.5 / s;
          return (
            <g key={`ui-${l.id}`}>
              {ghost && on && !isIdentity(l.pose) && (
                <rect className="tp-ghost" x={l.box.x} y={l.box.y} width={l.box.w} height={l.box.h} />
              )}
              <g transform={poseTransform(l.box, l.pose)}>
                <rect
                  className={["tp-box", on ? "tp-box--on" : "tp-box--off", invalid === l.id ? "tp-box--invalid" : ""].join(" ")}
                  width={l.box.w}
                  height={l.box.h}
                  strokeWidth={stroke}
                  tabIndex={on ? 0 : -1}
                  aria-label={on ? `${l.label ?? "Design"} position — drag to move, arrow keys to nudge` : `Select ${l.label}`}
                  onPointerDown={(e) =>
                    on ? start(e, { kind: "move", id: l.id, start: toPhoto(e), pose: l.pose }) : onSelect?.(l.id)
                  }
                  onKeyDown={(e) => nudge(e, l)}
                />
                {on && (
                  <>
                    <line className="tp-stem" x1={l.box.w / 2} y1={0} x2={l.box.w / 2} y2={-22 / s} strokeWidth={stroke} />
                    <circle
                      className="tp-handle tp-handle--rotate"
                      cx={l.box.w / 2}
                      cy={-22 / s}
                      r={halfHandle * 1.1}
                      strokeWidth={stroke}
                      onPointerDown={(e) => start(e, { kind: "rotate", id: l.id, pose: l.pose })}
                    >
                      <title>Drag to rotate</title>
                    </circle>
                    {[
                      [0, 0],
                      [l.box.w, 0],
                      [l.box.w, l.box.h],
                      [0, l.box.h],
                    ].map(([x, y]) => (
                      <rect
                        key={`${x}-${y}`}
                        className="tp-handle tp-handle--scale"
                        x={x - halfHandle}
                        y={y - halfHandle}
                        width={halfHandle * 2}
                        height={halfHandle * 2}
                        strokeWidth={stroke}
                        onPointerDown={(e) => start(e, { kind: "scale", id: l.id, pose: l.pose })}
                      >
                        <title>Drag to resize</title>
                      </rect>
                    ))}
                  </>
                )}
                {!on && l.label && (
                  <text className="tp-tag" x={4 / s} y={-6 / s} fontSize={(size.w > 600 ? 18 : 11) / s}>
                    {l.label}
                  </text>
                )}
              </g>
            </g>
          );
        })}
    </svg>
  );
}
