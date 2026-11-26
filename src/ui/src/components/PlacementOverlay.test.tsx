import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { BoundingBox } from "../types";
import { PlacementOverlay } from "./PlacementOverlay";

/** The mask brush's pointer handling: one pointer paints one stroke. */

const BOX: BoundingBox = [
  { x: 10, y: 10 },
  { x: 90, y: 10 },
  { x: 90, y: 90 },
  { x: 10, y: 90 },
];

/** jsdom has no SVG geometry: identity, so client pixels are photo pixels. */
function stubSvgGeometry(): () => void {
  const proto = SVGSVGElement.prototype as unknown as {
    createSVGPoint: () => DOMPoint;
    getScreenCTM: () => DOMMatrix | null;
  };
  const original = { point: proto.createSVGPoint, ctm: proto.getScreenCTM };
  proto.createSVGPoint = () => {
    const p = { x: 0, y: 0, matrixTransform: () => ({ x: p.x, y: p.y }) };
    return p as unknown as DOMPoint;
  };
  proto.getScreenCTM = () => ({ inverse: () => ({}) }) as unknown as DOMMatrix;
  return () => {
    proto.createSVGPoint = original.point;
    proto.getScreenCTM = original.ctm;
  };
}

function brush(onStroke: ReturnType<typeof vi.fn>, editing: boolean) {
  return (
    <svg>
      <PlacementOverlay
        box={BOX}
        designUrl="design.png"
        maskUrl={null}
        automaticMaskUrl={null}
        undoBases={[]}
        operations={[]}
        space={[100, 100]}
        editing={editing}
        mode="mask"
        diameter={8}
        onStroke={onStroke}
      />
    </svg>
  );
}

function renderBrush(onStroke = vi.fn()) {
  const { rerender } = render(brush(onStroke, true));
  return {
    onStroke,
    area: screen.getByLabelText("Mask drawing area"),
    stopEditing: () => rerender(brush(onStroke, false)),
  };
}

describe("PlacementOverlay's mask brush", () => {
  let restore = () => {};
  beforeEach(() => {
    restore = stubSvgGeometry();
  });
  afterEach(() => restore());

  const down = (area: Element, pointerId: number, x: number, y: number) =>
    fireEvent.pointerDown(area, { button: 0, pointerId, clientX: x, clientY: y });
  const move = (area: Element, pointerId: number, x: number, y: number) =>
    fireEvent.pointerMove(area, { pointerId, clientX: x, clientY: y });

  it("paints one finger's stroke", () => {
    const { onStroke, area } = renderBrush();
    down(area, 1, 20, 20);
    move(area, 1, 30, 30);
    fireEvent.pointerUp(area, { pointerId: 1 });
    expect(onStroke).toHaveBeenCalledWith({
      type: "stroke",
      mode: "mask",
      diameter_px: 8,
      points: [
        [20, 20],
        [30, 30],
      ],
    });
  });

  it("drops the stroke when a second finger lands, so a pinch paints nothing", () => {
    const { onStroke, area } = renderBrush();
    down(area, 1, 40, 50);
    down(area, 2, 60, 55);
    move(area, 1, 30, 45);
    move(area, 2, 70, 60);
    fireEvent.pointerUp(area, { pointerId: 2 });
    fireEvent.pointerUp(area, { pointerId: 1 });
    expect(onStroke).not.toHaveBeenCalled();

    // Once the fingers lift, one finger paints again.
    down(area, 3, 20, 20);
    fireEvent.pointerUp(area, { pointerId: 3 });
    expect(onStroke).toHaveBeenCalledOnce();
  });

  it("commits a stroke under way once when mask mode ends mid-press", () => {
    const { onStroke, area, stopEditing } = renderBrush();
    down(area, 1, 20, 20);
    move(area, 1, 30, 30);
    stopEditing();
    expect(onStroke).toHaveBeenCalledOnce();
    expect(onStroke.mock.lastCall?.[0]).toMatchObject({
      points: [
        [20, 20],
        [30, 30],
      ],
    });
  });

  it("ignores another pointer's release while a stroke is under way", () => {
    const { onStroke, area } = renderBrush();
    down(area, 1, 20, 20);
    fireEvent.lostPointerCapture(area, { pointerId: 2 });
    move(area, 1, 25, 25);
    fireEvent.pointerUp(area, { pointerId: 1 });
    const [stroke] = onStroke.mock.calls[0] ?? [];
    expect(stroke.points).toHaveLength(2);
  });
});
