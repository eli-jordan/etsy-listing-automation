import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { drag, zoomedTo } from "../test/touch";
import { ownedElsewhere, type SwipeOptions, useSwipe } from "./useSwipe";

function mount(html: string): HTMLElement {
  const root = document.createElement("div");
  root.innerHTML = html;
  document.body.append(root);
  return root;
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

function fingerless(element: Element, type: string, x: number) {
  const event = new PointerEvent(type, {
    bubbles: true,
    clientX: x,
    clientY: 100,
    pointerType: "mouse",
  });
  Object.defineProperty(event, "isPrimary", { value: true });
  element.dispatchEvent(event);
}

function swiping(axis: "x" | "y" = "x") {
  const element = mount("");
  element.style.touchAction = "manipulation";
  const options: SwipeOptions = { axis, onDrag: vi.fn(), onEnd: vi.fn(), enabled: true };
  const hook = renderHook(() => useSwipe({ current: element }, options));
  return { element, options, ...hook };
}

describe("useSwipe", () => {
  it("claims touches on its own axis, leaving the other axis and pinch-zoom to the browser", () => {
    expect(swiping("x").element.style.touchAction).toBe("pan-y pinch-zoom");
    expect(swiping("y").element.style.touchAction).toBe("pan-x pinch-zoom");
  });

  it("leaves every touch to the browser while the page is pinch-zoomed", () => {
    zoomedTo(2);
    const { element, options } = swiping();
    expect(element.style.touchAction).toBe("manipulation");
    drag(element, [200, 100], [40, 100]);
    expect(options.onEnd).not.toHaveBeenCalled();
  });

  it("hands the pan back on the next touch after a pinch that fired no resize", () => {
    const { element } = swiping();
    zoomedTo(2);
    drag(element, [200, 100], [40, 100]);
    expect(element.style.touchAction).toBe("manipulation");
  });

  it("says nothing for a move along the other axis", () => {
    const { element, options } = swiping("x");
    drag(element, [100, 50], [100, 250]);
    expect(options.onDrag).not.toHaveBeenCalled();
    expect(options.onEnd).not.toHaveBeenCalled();
  });

  it("ends a cancelled touch with no swipe", () => {
    const { element, options } = swiping("x");
    for (const [type, x] of [
      ["pointerdown", 200],
      ["pointermove", 120],
      ["pointermove", 40],
      ["pointercancel", 40],
    ] as const) {
      const event = new PointerEvent(type, {
        bubbles: true,
        clientX: x,
        clientY: 100,
        pointerId: 99,
        pointerType: "touch",
      });
      Object.defineProperty(event, "isPrimary", { value: true });
      element.dispatchEvent(event);
    }
    expect(options.onDrag).toHaveBeenCalled();
    expect(options.onEnd).toHaveBeenCalledWith(null);
  });

  it("ignores a mouse drag", () => {
    const { element, options } = swiping("x");
    for (const [type, x] of [
      ["pointerdown", 200],
      ["pointermove", 120],
      ["pointermove", 20],
      ["pointerup", 20],
    ] as const)
      fingerless(element, type, x);
    expect(options.onDrag).not.toHaveBeenCalled();
    expect(options.onEnd).not.toHaveBeenCalled();
  });
});

describe("ownedElsewhere", () => {
  it("lets a swipe start on plain content", () => {
    const root = mount("<p>Brief</p>");
    expect(ownedElsewhere(root.querySelector("p"), root, "x")).toBe(false);
  });

  it("lets a swipe start on a field nobody is typing in", () => {
    const root = mount('<input value="Raccoon Shirt" /><textarea>brief</textarea>');
    expect(ownedElsewhere(root.querySelector("input"), root, "x")).toBe(false);
    expect(ownedElsewhere(root.querySelector("textarea"), root, "x")).toBe(false);
  });

  it("leaves the field being typed in to its caret", () => {
    const root = mount('<input value="Raccoon Shirt" />');
    const field = root.querySelector("input");
    field?.focus();
    expect(ownedElsewhere(field, root, "x")).toBe(true);
  });

  it("leaves sliders and marked areas to their own drag", () => {
    const root = mount(
      '<input type="range" /><div role="slider"></div><div data-swipe-ignore><span>tile</span></div>',
    );
    expect(ownedElsewhere(root.querySelector("input"), root, "x")).toBe(true);
    expect(ownedElsewhere(root.querySelector("[role=slider]"), root, "x")).toBe(true);
    expect(ownedElsewhere(root.querySelector("span"), root, "x")).toBe(true);
  });

  it("leaves a draggable divider to its own drag", () => {
    const root = mount('<div role="separator" tabindex="0"><span>edge</span></div>');
    expect(ownedElsewhere(root.querySelector("span"), root, "x")).toBe(true);
  });
});
