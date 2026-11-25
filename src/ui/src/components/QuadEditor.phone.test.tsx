import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PHONE_QUERY } from "../phone/usePhone";
import type { BoundingBox } from "../types";
import { QuadEditor } from "./QuadEditor";

/** The phone layout's additions to the canvas: finger-sized grips over the
 * corner dots, and the box actions a right-click gives on the desktop. */

const BOX: BoundingBox = [
  { x: 0, y: 0 },
  { x: 100, y: 0 },
  { x: 100, y: 100 },
  { x: 0, y: 100 },
];

function stubPhone(matches: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: matches && query === PHONE_QUERY,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

function renderQuad(extra: Partial<Parameters<typeof QuadEditor>[0]> = {}) {
  const result = render(
    <QuadEditor
      imageUrl="preview.png"
      space={[400, 200]}
      boxes={[BOX]}
      selectedIndex={0}
      onSelect={vi.fn()}
      onChangeBox={vi.fn()}
      {...extra}
    />,
  );
  fireEvent.load(screen.getByAltText("Rendered preview"));
  return result;
}

describe("QuadEditor on a phone", () => {
  beforeEach(() => stubPhone(true));
  afterEach(() => vi.unstubAllGlobals());

  it("lays a grip over each corner of the selected box", () => {
    const { container } = renderQuad();
    const grips = container.querySelectorAll(".quad-editor__grip");
    expect(grips).toHaveLength(4);
    expect(grips[2]?.getAttribute("cx")).toBe("100");
  });

  it("sizes each grip to 22 screen pixels and keeps an edge corner's grip whole", () => {
    // The photo's 400 image pixels shown 200 wide: 22 screen px is 44 units.
    const rect = vi
      .spyOn(SVGElement.prototype, "getBoundingClientRect")
      .mockReturnValue(new DOMRect(0, 0, 200, 100));
    const { container } = renderQuad();
    rect.mockRestore();
    const grips = container.querySelectorAll(".quad-editor__grip");
    expect(grips[2]?.getAttribute("r")).toBe("44");
    expect(grips[2]?.getAttribute("cx")).toBe("100");
    // The corner at the photo's top-left: pulled in by its radius.
    expect(grips[0]?.getAttribute("cx")).toBe("44");
    expect(grips[0]?.getAttribute("cy")).toBe("44");
  });

  it("keeps a touch that lands on the box or a grip from scrolling the page", () => {
    const { container } = renderQuad();
    const touch = (target: Element) => {
      const event = new Event("touchstart", { bubbles: true, cancelable: true });
      target.dispatchEvent(event);
      return event.defaultPrevented;
    };
    expect(touch(container.querySelector(".quad-editor__polygon") as Element)).toBe(true);
    expect(touch(container.querySelector(".quad-editor__grip") as Element)).toBe(true);
    // Elsewhere on the photo a finger still scrolls.
    expect(touch(container.querySelector(".quad-editor__overlay") as Element)).toBe(false);
  });

  it("draws no grips while the canvas is not taking edits", () => {
    const { container } = renderQuad({ interactive: false });
    expect(container.querySelectorAll(".quad-editor__grip")).toHaveLength(0);
  });

  it("offers add, duplicate and delete as buttons under the photo", () => {
    const onAddBox = vi.fn();
    const onDeleteSelected = vi.fn();
    const onDuplicateSelected = vi.fn();
    const { container } = renderQuad({ onAddBox, onDeleteSelected, onDuplicateSelected });
    const toolbar = screen.getByRole("toolbar", { name: "Boxes" });
    // Outside the canvas, whose overlay stretches over anything inside it.
    expect(container.querySelector(".quad-editor")?.contains(toolbar)).toBe(false);
    expect(container.querySelector(".quad-editor__add")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "+ Add box" }));
    fireEvent.click(screen.getByRole("button", { name: "Duplicate" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onAddBox).toHaveBeenCalledOnce();
    expect(onDuplicateSelected).toHaveBeenCalledOnce();
    expect(onDeleteSelected).toHaveBeenCalledOnce();
  });

  it("has no action row for a kind with one fixed box", () => {
    renderQuad();
    expect(screen.queryByRole("toolbar", { name: "Boxes" })).toBeNull();
  });

  it("gives the action row's Delete its own danger style, not the menu's", () => {
    renderQuad({ onAddBox: vi.fn(), onDeleteSelected: vi.fn() });
    const remove = screen.getByRole("button", { name: "Delete" });
    expect(remove).toHaveClass("quad-editor__phone-danger");
    expect(remove).not.toHaveClass("quad-editor__menu-danger");
  });
});

describe("QuadEditor off the phone", () => {
  beforeEach(() => stubPhone(false));
  afterEach(() => vi.unstubAllGlobals());

  it("keeps the desktop canvas: no grips, Add box on the photo, no action row", () => {
    const { container } = renderQuad({ onAddBox: vi.fn(), onDeleteSelected: vi.fn() });
    expect(container.querySelectorAll(".quad-editor__grip")).toHaveLength(0);
    expect(container.querySelector(".quad-editor .quad-editor__add")).not.toBeNull();
    expect(screen.queryByRole("toolbar", { name: "Boxes" })).toBeNull();
  });

  it("leaves touches on the box to the browser", () => {
    const { container } = renderQuad();
    const event = new Event("touchstart", { bubbles: true, cancelable: true });
    container.querySelector(".quad-editor__polygon")?.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
  });
});
