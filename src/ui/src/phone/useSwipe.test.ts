import { afterEach, describe, expect, it } from "vitest";
import { ownedElsewhere } from "./useSwipe";

function mount(html: string): HTMLElement {
  const root = document.createElement("div");
  root.innerHTML = html;
  document.body.append(root);
  return root;
}

afterEach(() => {
  document.body.innerHTML = "";
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
