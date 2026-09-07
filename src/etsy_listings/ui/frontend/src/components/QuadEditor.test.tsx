import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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

  describe("the box context menu", () => {
    const rect = (left: number, top: number, width: number, height: number): DOMRect =>
      ({
        left,
        top,
        width,
        height,
        right: left + width,
        bottom: top + height,
        x: left,
        y: top,
        toJSON: () => ({}),
      }) as DOMRect;

    const MENU_W = 150;
    const MENU_H = 90;

    /** jsdom reports every rect as zero-sized, so the three things the
     * positioning measures -- the canvas, the menu, and the clipping ancestor
     * -- have to be given sizes for the test to mean anything.
     *
     * Patched on the prototype rather than per node, because the menu is
     * measured inside a layout effect the moment it mounts: there is no point
     * at which a test could hold the node and still be ahead of it.
     *
     * The clip box is deliberately *shorter* than the canvas. That gap is
     * what the first attempt at this got wrong -- it measured against the
     * canvas, so the vertical overflow went unnoticed.
     */
    function sizeEverything({ clipW = 400, clipH = 200 } = {}) {
      vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (
        this: Element,
      ) {
        if (this.classList.contains("quad-editor__menu")) {
          const style = (this as HTMLElement).style;
          return rect(parseFloat(style.left || "0"), parseFloat(style.top || "0"), MENU_W, MENU_H);
        }
        if (this.tagName.toLowerCase() === "svg") return rect(0, 0, 400, 400);
        return rect(0, 0, clipW, clipH);
      });
    }

    function renderWithMenu() {
      render(
        <QuadEditor
          imageUrl="preview.png"
          boxes={[BOX_A]}
          selectedIndex={0}
          onSelect={vi.fn()}
          onChangeBox={vi.fn()}
          onDuplicateSelected={vi.fn()}
          onBringSelectedToFront={vi.fn()}
          onDeleteSelected={vi.fn()}
        />,
      );
      loadImage();
      sizeEverything();
      return must(document.querySelector(".quad-editor__box"));
    }

    function openAt(box: Element, clientX: number, clientY: number) {
      fireEvent.contextMenu(box, { clientX, clientY });
      const menu = must(document.querySelector<HTMLElement>(".quad-editor__menu"));
      return {
        left: parseFloat(menu.style.left),
        top: parseFloat(menu.style.top),
        right: parseFloat(menu.style.left) + MENU_W,
        bottom: parseFloat(menu.style.top) + MENU_H,
        el: menu,
      };
    }

    it("opens with all three actions", () => {
      const { el } = openAt(renderWithMenu(), 20, 20);
      expect([...el.querySelectorAll('[role="menuitem"]')].map((b) => b.textContent)).toEqual([
        "Duplicate",
        "Bring to front",
        "Delete ⌫",
      ]);
    });

    it("opens at the click when there is room", () => {
      const menu = openAt(renderWithMenu(), 20, 20);
      expect([menu.left, menu.top]).toEqual([20, 20]);
    });

    it("stays inside the clip box when opened near the far corner", () => {
      /* The bug: `.app__preview` clips its overflow, so a menu opening
       * right-and-down from the rightmost box had two of its three items cut
       * off -- "Delete" was unreachable for the last garment in a chart. */
      const menu = openAt(renderWithMenu(), 380, 190);
      expect(menu.right).toBeLessThanOrEqual(400);
      expect(menu.bottom).toBeLessThanOrEqual(200);
    });

    it("pulls back on each axis independently", () => {
      const menu = openAt(renderWithMenu(), 380, 20);
      expect(menu.right).toBeLessThanOrEqual(400);
      expect(menu.top).toBe(20); // vertical had room; left alone
    });

    it("pulls back vertically even when the click is above the canvas midpoint", () => {
      /* The clip box is shorter than the canvas, so "past the midpoint of the
       * canvas" is the wrong question -- a click at 40% of a 400px canvas
       * still overflows a 200px clip box. Measuring is the point. */
      const menu = openAt(renderWithMenu(), 20, 160);
      expect(menu.bottom).toBeLessThanOrEqual(200);
      expect(menu.top).toBeLessThan(160);
    });

    it("is not offered when the editor has no box actions", () => {
      render(
        <QuadEditor
          imageUrl="preview.png"
          boxes={[BOX_A]}
          selectedIndex={0}
          onSelect={vi.fn()}
          onChangeBox={vi.fn()}
        />,
      );
      loadImage();
      fireEvent.contextMenu(must(document.querySelector(".quad-editor__box")), {
        clientX: 20,
        clientY: 20,
      });
      expect(document.querySelector(".quad-editor__menu")).toBeNull();
    });
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

/** jsdom implements no SVG geometry, so the two calls the editor maps screen
 * pixels through have to be supplied. Identity, so image space *is* client
 * space and the arithmetic in the assertions stays readable. */
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

describe("sliding a whole box", () => {
  let restore = () => {};
  beforeEach(() => {
    restore = stubSvgGeometry();
  });
  afterEach(() => restore());

  function renderDraggable(onChangeBox = vi.fn(), onSelect = vi.fn()) {
    const { container } = render(
      <QuadEditor
        imageUrl="preview.png"
        boxes={[BOX_A, BOX_B]}
        selectedIndex={0}
        onSelect={onSelect}
        onChangeBox={onChangeBox}
      />,
    );
    loadImage();
    return container;
  }

  const overlay = (container: HTMLElement) =>
    must(container.querySelector(".quad-editor__overlay"));

  const press = (target: Element, clientX: number, clientY: number, button = 0) =>
    fireEvent.pointerDown(target, { button, clientX, clientY, pointerId: 1 });

  it("dragging inside a box translates all four corners by the same delta", () => {
    const onChangeBox = vi.fn();
    const container = renderDraggable(onChangeBox);
    press(must(container.querySelector(".quad-editor__polygon")), 10, 10);
    fireEvent.pointerMove(overlay(container), { clientX: 40, clientY: 25 });

    expect(onChangeBox).toHaveBeenCalledWith(0, [
      { x: 30, y: 15 },
      { x: 130, y: 15 },
      { x: 130, y: 115 },
      { x: 30, y: 115 },
    ]);
  });

  it("pressing a dimmed box selects it and drags that one", () => {
    const onChangeBox = vi.fn();
    const onSelect = vi.fn();
    const container = renderDraggable(onChangeBox, onSelect);
    press(must(container.querySelectorAll(".quad-editor__polygon")[1]), 0, 0);
    expect(onSelect).toHaveBeenCalledWith(1);

    fireEvent.pointerMove(overlay(container), { clientX: 5, clientY: 0 });
    const [index] = must(onChangeBox.mock.calls[0]);
    expect(index).toBe(1);
  });

  it("stops moving once the pointer is released", () => {
    const onChangeBox = vi.fn();
    const container = renderDraggable(onChangeBox);
    press(must(container.querySelector(".quad-editor__polygon")), 0, 0);
    fireEvent.pointerUp(overlay(container));
    fireEvent.pointerMove(overlay(container), { clientX: 90, clientY: 90 });
    expect(onChangeBox).not.toHaveBeenCalled();
  });

  it("ignores a right-press, which is the context-menu gesture", () => {
    const onChangeBox = vi.fn();
    const container = renderDraggable(onChangeBox);
    press(must(container.querySelector(".quad-editor__polygon")), 0, 0, 2);
    fireEvent.pointerMove(overlay(container), { clientX: 90, clientY: 90 });
    expect(onChangeBox).not.toHaveBeenCalled();
  });
});

describe("the on-canvas box captions", () => {
  function renderLabelled(props: Partial<Parameters<typeof QuadEditor>[0]> = {}) {
    const onLabelChange = vi.fn();
    const view = render(
      <QuadEditor
        imageUrl="preview.png"
        boxes={[BOX_A, BOX_B]}
        selectedIndex={0}
        onSelect={vi.fn()}
        onChangeBox={vi.fn()}
        labels={["black", ""]}
        onLabelChange={onLabelChange}
        labelPlaceholder="assign colour…"
        labelSuggestions={["ivory"]}
        {...props}
      />,
    );
    loadImage();
    return { ...view, onLabelChange };
  }

  it("captions every box, and prompts on the ones with no colour", () => {
    renderLabelled();
    expect(screen.getByRole("button", { name: "black" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "assign colour…" })).toBeInTheDocument();
  });

  it("positions a caption under its box, in percentages of the image", () => {
    const { container } = renderLabelled();
    // BOX_A spans x 0-100 of a 400px-wide image, and reaches y 100 of 200.
    const caption = must(container.querySelector<HTMLElement>(".quad-editor__label"));
    expect(caption.style.left).toBe("12.5%");
    expect(caption.style.top).toBe("50%");
  });

  it("clicking a caption opens it for editing and reports what is typed", () => {
    const { onLabelChange } = renderLabelled();
    fireEvent.click(screen.getByRole("button", { name: "black" }));
    const field = screen.getByLabelText("Colour for box 1");
    expect(field).toHaveFocus();

    fireEvent.change(field, { target: { value: "moss" } });
    expect(onLabelChange).toHaveBeenCalledWith(0, "moss");
  });

  it("Enter closes the editor", () => {
    renderLabelled();
    fireEvent.click(screen.getByRole("button", { name: "black" }));
    fireEvent.keyDown(screen.getByLabelText("Colour for box 1"), { key: "Enter" });
    expect(screen.queryByLabelText("Colour for box 1")).not.toBeInTheDocument();
  });

  it("arrow keys typed into a caption do not nudge the box", () => {
    const onChangeBox = vi.fn();
    const onDeleteSelected = vi.fn();
    renderLabelled({ onChangeBox, onDeleteSelected });
    fireEvent.click(screen.getByRole("button", { name: "black" }));
    const field = screen.getByLabelText("Colour for box 1");
    fireEvent.keyDown(field, { key: "ArrowRight" });
    fireEvent.keyDown(field, { key: "Backspace" });
    expect(onChangeBox).not.toHaveBeenCalled();
    expect(onDeleteSelected).not.toHaveBeenCalled();
  });

  it("hiding the chrome hides the captions with the outlines", () => {
    const { container } = renderLabelled({ outlines: "none" });
    expect(container.querySelectorAll(".quad-editor__label")).toHaveLength(0);
  });

  it("with only the selected outline shown, only its caption is", () => {
    const { container } = renderLabelled({ outlines: "selected" });
    expect(container.querySelectorAll(".quad-editor__label")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "black" })).toBeInTheDocument();
  });
});
