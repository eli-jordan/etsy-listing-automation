import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { must } from "../test/helpers";
import type { BoundingBox } from "../types";
import { QuadEditor } from "./QuadEditor";

const BOX_A: BoundingBox = [
  { x: 0, y: 0 },
  { x: 100, y: 0 },
  { x: 100, y: 100 },
  { x: 0, y: 100 },
];
const BOX_B: BoundingBox = [
  { x: 200, y: 0 },
  { x: 300, y: 0 },
  { x: 300, y: 100 },
  { x: 200, y: 100 },
];

function loadImage() {
  const img = screen.getByAltText("Rendered preview");
  Object.defineProperty(img, "naturalWidth", { value: 400, configurable: true });
  Object.defineProperty(img, "naturalHeight", { value: 200, configurable: true });
  fireEvent.load(img);
}

describe("QuadEditor", () => {
  it("renders no overlay until the image has loaded", () => {
    const { container } = render(
      <QuadEditor
        imageUrl="preview.png"
        boxes={[BOX_A]}
        selectedIndex={0}
        onSelect={vi.fn()}
        onChangeBox={vi.fn()}
      />,
    );
    expect(container.querySelector(".quad-editor__overlay")).toBeNull();
  });

  it("renders one box group per box, once loaded", () => {
    const { container } = render(
      <QuadEditor
        imageUrl="preview.png"
        boxes={[BOX_A, BOX_B]}
        selectedIndex={0}
        onSelect={vi.fn()}
        onChangeBox={vi.fn()}
      />,
    );
    loadImage();
    expect(container.querySelectorAll(".quad-editor__box")).toHaveLength(2);
  });

  it("clicking a non-selected box calls onSelect with its index", () => {
    const onSelect = vi.fn();
    const { container } = render(
      <QuadEditor
        imageUrl="preview.png"
        boxes={[BOX_A, BOX_B]}
        selectedIndex={0}
        onSelect={onSelect}
        onChangeBox={vi.fn()}
      />,
    );
    loadImage();
    const groups = container.querySelectorAll(".quad-editor__box");
    fireEvent.click(must(groups[1]));
    expect(onSelect).toHaveBeenCalledWith(1);
  });

  it("only the selected box shows drag handles", () => {
    const { container } = render(
      <QuadEditor
        imageUrl="preview.png"
        boxes={[BOX_A, BOX_B]}
        selectedIndex={1}
        onSelect={vi.fn()}
        onChangeBox={vi.fn()}
      />,
    );
    loadImage();
    // 4 handles total, all belonging to the selected (second) box.
    expect(container.querySelectorAll(".quad-editor__handle")).toHaveLength(4);
    const groups = container.querySelectorAll(".quad-editor__box");
    expect(must(groups[0]).querySelectorAll(".quad-editor__handle")).toHaveLength(0);
    expect(must(groups[1]).querySelectorAll(".quad-editor__handle")).toHaveLength(4);
  });

  it("arrow key nudges the selected box by one pixel", () => {
    const onChangeBox = vi.fn();
    render(
      <QuadEditor
        imageUrl="preview.png"
        boxes={[BOX_A]}
        selectedIndex={0}
        onSelect={vi.fn()}
        onChangeBox={onChangeBox}
      />,
    );
    loadImage();
    fireEvent.keyDown(screen.getByAltText("Rendered preview").parentElement as HTMLElement, {
      key: "ArrowRight",
    });
    expect(onChangeBox).toHaveBeenCalledWith(0, [
      { x: 1, y: 0 },
      { x: 101, y: 0 },
      { x: 101, y: 100 },
      { x: 1, y: 100 },
    ]);
  });

  it("shift+arrow nudges by the fast step", () => {
    const onChangeBox = vi.fn();
    render(
      <QuadEditor
        imageUrl="preview.png"
        boxes={[BOX_A]}
        selectedIndex={0}
        onSelect={vi.fn()}
        onChangeBox={onChangeBox}
      />,
    );
    loadImage();
    fireEvent.keyDown(screen.getByAltText("Rendered preview").parentElement as HTMLElement, {
      key: "ArrowDown",
      shiftKey: true,
    });
    const [, box] = must(onChangeBox.mock.calls[0]);
    expect(must(box[0]).y).toBe(8);
  });

  it("a non-arrow key is a no-op", () => {
    const onChangeBox = vi.fn();
    render(
      <QuadEditor
        imageUrl="preview.png"
        boxes={[BOX_A]}
        selectedIndex={0}
        onSelect={vi.fn()}
        onChangeBox={onChangeBox}
      />,
    );
    loadImage();
    fireEvent.keyDown(screen.getByAltText("Rendered preview").parentElement as HTMLElement, {
      key: "a",
    });
    expect(onChangeBox).not.toHaveBeenCalled();
  });
});
