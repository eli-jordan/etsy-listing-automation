import { maskDraft } from "./maskDraft";
import { useId, useRef, useState } from "react";
import type { MaskOperation } from "../api/preparation";
import type { BoundingBox } from "../types";
import { artworkTransform } from "./artworkTransform";

export type Stroke = Extract<MaskOperation, { type: "stroke" }>;
/** Mask pixels and strokes use original photo coordinates. The separate SVG
 * input layer captures a complete gesture so moving a placement cannot move
 * a saved exclusion and Undo never removes only part of a stroke. */
export function PlacementOverlay({
  box,
  designUrl,
  maskUrl,
  automaticMaskUrl,
  undoBases,
  operations,
  space,
  editing,
  mode,
  diameter,
  onStroke,
}: {
  box: BoundingBox;
  designUrl: string;
  maskUrl: string | null;
  automaticMaskUrl: string | null;
  undoBases: string[];
  operations: MaskOperation[];
  space: [number, number];
  editing: boolean;
  mode: "mask" | "unmask";
  diameter: number;
  onStroke: (stroke: Stroke) => void;
}) {
  const id = useId().replaceAll(":", "");
  const [stroke, setStroke] = useState<Stroke | null>(null);
  const current = useRef<Stroke | null>(null);
  const { automatic, strokes, undoSaved } = maskDraft(operations);
  const base = automatic
    ? automaticMaskUrl
    : undoSaved
      ? undoBases[undoBases.length - undoSaved]
        ? `data:image/png;base64,${undoBases[undoBases.length - undoSaved]}`
        : maskUrl
      : maskUrl;
  function point(event: React.PointerEvent<SVGRectElement>): [number, number] | null {
    const svg = event.currentTarget.ownerSVGElement;
    const ctm = svg?.getScreenCTM();
    if (!svg || !ctm) return null;
    const p = svg.createSVGPoint();
    p.x = event.clientX;
    p.y = event.clientY;
    const result = p.matrixTransform(ctm.inverse());
    return [
      Math.max(0, Math.min(space[0] - 1, result.x)),
      Math.max(0, Math.min(space[1] - 1, result.y)),
    ];
  }
  function finish() {
    const next = current.current;
    current.current = null;
    setStroke(null);
    if (next) onStroke(next);
  }
  const all = stroke ? [...strokes, stroke] : strokes;
  const paths = all.map((s, i) => (
    <path
      key={i}
      d={
        s.points.map((p, j) => `${j ? "L" : "M"}${p[0]},${p[1]}`).join(" ") +
        (s.points.length === 1 ? ` l0.001,0` : "")
      }
      stroke={s.mode === "mask" ? "black" : "white"}
      strokeWidth={s.diameter_px}
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
  ));
  return (
    <g>
      <defs>
        <mask
          id={`cloth-${id}`}
          maskUnits="userSpaceOnUse"
          x={0}
          y={0}
          width={space[0]}
          height={space[1]}
        >
          <rect width={space[0]} height={space[1]} fill="white" />
          {base && <image href={base} width={space[0]} height={space[1]} />} {paths}
        </mask>
        <filter id={`invert-${id}`}>
          <feComponentTransfer>
            <feFuncR type="table" tableValues="1 0" />
            <feFuncG type="table" tableValues="1 0" />
            <feFuncB type="table" tableValues="1 0" />
          </feComponentTransfer>
        </filter>
        <mask
          id={`hidden-${id}`}
          maskUnits="userSpaceOnUse"
          x={0}
          y={0}
          width={space[0]}
          height={space[1]}
        >
          <g filter={`url(#invert-${id})`}>
            <rect width={space[0]} height={space[1]} fill="white" />
            {base && <image href={base} width={space[0]} height={space[1]} />} {paths}
          </g>
        </mask>
      </defs>
      <g mask={`url(#cloth-${id})`} pointerEvents="none">
        <foreignObject
          x={0}
          y={0}
          width={space[0]}
          height={space[1]}
          style={{ overflow: "visible" }}
        >
          <img
            src={designUrl}
            alt=""
            style={{
              width: 1,
              height: 1,
              position: "absolute",
              transformOrigin: "0 0",
              transform: artworkTransform(box),
              pointerEvents: "none",
            }}
          />
        </foreignObject>
      </g>
      {editing && (
        <>
          <rect
            width={space[0]}
            height={space[1]}
            fill="#e43737"
            opacity={0.32}
            mask={`url(#hidden-${id})`}
            pointerEvents="none"
          />
          <rect
            aria-label="Mask drawing area"
            width={space[0]}
            height={space[1]}
            fill="transparent"
            style={{ touchAction: "none", cursor: "crosshair" }}
            onPointerDown={(event) => {
              if (event.button !== 0) return;
              event.stopPropagation();
              const p = point(event);
              if (!p) return;
              event.currentTarget.setPointerCapture(event.pointerId);
              const next: Stroke = { type: "stroke", mode, diameter_px: diameter, points: [p] };
              current.current = next;
              setStroke(next);
            }}
            onPointerMove={(event) => {
              if (!current.current) return;
              event.stopPropagation();
              const p = point(event);
              if (p) {
                const next = { ...current.current, points: [...current.current.points, p] };
                current.current = next;
                setStroke(next);
              }
            }}
            onPointerUp={(event) => {
              event.stopPropagation();
              finish();
            }}
            onPointerCancel={finish}
          />
        </>
      )}
    </g>
  );
}
