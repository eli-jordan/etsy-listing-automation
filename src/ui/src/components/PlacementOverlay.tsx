import { maskDraft } from "./maskDraft";
import { useEffect, useEffectEvent, useId, useRef, useState } from "react";
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
  showArtwork = true,
}: {
  showArtwork?: boolean;
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
  const cursor = useRef<SVGGElement>(null);
  function hideCursor() {
    cursor.current?.setAttribute("visibility", "hidden");
  }
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
    if (result.x >= 0 && result.x < space[0] && result.y >= 0 && result.y < space[1]) {
      cursor.current?.setAttribute("transform", `translate(${result.x} ${result.y})`);
      cursor.current?.setAttribute("visibility", "visible");
    } else hideCursor();
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
  // Leaving mask mode commits an active gesture once, including Escape while
  // the pointer is still held. The effect event uses the latest draft callback.
  const finishGesture = useEffectEvent(finish);
  useEffect(() => {
    if (editing) return () => finishGesture();
  }, [editing]);
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
      {showArtwork && (
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
      )}
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
            style={{ touchAction: "none", cursor: "none" }}
            onPointerEnter={point}
            onPointerLeave={hideCursor}
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
              const p = point(event);
              if (!current.current) return;
              event.stopPropagation();
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
            onPointerCancel={() => {
              finish();
              hideCursor();
            }}
            onLostPointerCapture={finish}
          />
          <g
            ref={cursor}
            aria-label="Brush footprint"
            visibility="hidden"
            pointerEvents="none"
            fill="none"
          >
            {/* SVG photo units match the stroke, including resize and DPR.
                  Non-scaling outlines stay legible on light and dark photos. */}
            <circle
              cx={0}
              cy={0}
              r={(stroke?.diameter_px ?? diameter) / 2}
              stroke="black"
              strokeWidth={3}
              vectorEffect="non-scaling-stroke"
            />
            <circle
              cx={0}
              cy={0}
              r={(stroke?.diameter_px ?? diameter) / 2}
              stroke="white"
              strokeWidth={1}
              vectorEffect="non-scaling-stroke"
            />
          </g>
        </>
      )}
    </g>
  );
}
