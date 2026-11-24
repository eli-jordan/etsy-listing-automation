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
});
