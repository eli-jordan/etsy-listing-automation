import { useRef, useState } from "react";
import type { WarpConfig } from "../types";

type Point = [number, number];

interface Props {
  imageUrl: string;
  quad: WarpConfig["quad"];
  onChange: (quad: WarpConfig["quad"]) => void;
}

/**
 * Draggable four-corner quad overlaid on the (already-rendered) preview
 * image. The SVG's viewBox is set to the image's natural pixel size, so
 * screen-to-image coordinate mapping goes through the SVG's own CTM rather
 * than a hand-rolled scale factor -- correct regardless of how the browser
 * scales the displayed image.
 */
export function QuadEditor({ imageUrl, quad, onChange }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [naturalSize, setNaturalSize] = useState<[number, number] | null>(null);
  const [dragIndex, setDragIndex] = useState<number | null>(null);

  function toImageSpace(clientX: number, clientY: number): Point | null {
    const svg = svgRef.current;
    if (!svg) return null;
    const ctm = svg.getScreenCTM();
    if (!ctm) return null;
    const point = svg.createSVGPoint();
    point.x = clientX;
    point.y = clientY;
    const transformed = point.matrixTransform(ctm.inverse());
    return [transformed.x, transformed.y];
  }

  function handlePointerDown(index: number) {
    return (event: React.PointerEvent<SVGCircleElement>) => {
      event.currentTarget.setPointerCapture(event.pointerId);
      setDragIndex(index);
    };
  }

  function handlePointerMove(event: React.PointerEvent<SVGSVGElement>) {
    if (dragIndex === null) return;
    const point = toImageSpace(event.clientX, event.clientY);
    if (!point) return;
    const next = quad.map((p, i) => (i === dragIndex ? point : p)) as WarpConfig["quad"];
    onChange(next);
  }

  function handlePointerUp() {
    setDragIndex(null);
  }

  return (
    <div className="quad-editor">
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
          <polygon
            points={quad.map(([x, y]) => `${x},${y}`).join(" ")}
            className="quad-editor__polygon"
          />
          {quad.map(([x, y], index) => (
            <circle
              key={index}
              cx={x}
              cy={y}
              r={Math.max(naturalSize[0], naturalSize[1]) * 0.015}
              className="quad-editor__handle"
              onPointerDown={handlePointerDown(index)}
            />
          ))}
        </svg>
      )}
    </div>
  );
}
