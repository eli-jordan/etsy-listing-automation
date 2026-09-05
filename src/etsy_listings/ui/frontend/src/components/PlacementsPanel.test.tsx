import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { must } from "../test/helpers";
import type { BoundingBox, Placement } from "../types";
import { PlacementsPanel } from "./PlacementsPanel";

function box(x: number, y: number, w = 100, h = 80): BoundingBox {
  return [
    { x, y },
    { x: x + w, y },
    { x: x + w, y: y + h },
    { x, y: y + h },
  ];
}

const PLACEMENTS: Placement[] = [
  { colour: "sand", bounding_box: box(0, 0), artwork: null },
  { colour: "black", bounding_box: box(200, 0), artwork: null },
];

function renderPanel(over: Partial<Parameters<typeof PlacementsPanel>[0]> = {}) {
  const onChange = vi.fn();
  const onSelect = vi.fn();
  render(
    <PlacementsPanel
      placements={PLACEMENTS}
      selectedIndex={0}
      onSelect={onSelect}
      onChange={onChange}
      knownColours={["sand", "black", "navy"]}
      {...over}
    />,
  );
  return { onChange, onSelect };
}

describe("PlacementsPanel", () => {
  it("lists every box with its number and colour", () => {
    renderPanel();
    expect(screen.getByText("1 · sand")).toBeInTheDocument();
    expect(screen.getByText("2 · black")).toBeInTheDocument();
  });

  it("counts the boxes in the heading", () => {
    renderPanel();
    expect(screen.getByText("Bounding boxes · 2")).toBeInTheDocument();
  });

  it("calls an uncoloured box what it is, rather than showing a blank", () => {
    renderPanel({ placements: [{ colour: "", bounding_box: box(0, 0), artwork: null }] });
    expect(screen.getByText("1 · new box")).toBeInTheDocument();
  });

  it("warns when a box has no colour, in the same words the rail uses", () => {
    renderPanel({
      placements: [...PLACEMENTS, { colour: "", bounding_box: box(0, 0), artwork: null }],
    });
    // Same derivation as TemplateSummary.status_reason, so the panel and the
    // rail can never disagree about whether this template is finished.
    expect(screen.getByText(/1 box has no colour/)).toBeInTheDocument();
  });

  it("is plural-aware about that warning", () => {
    renderPanel({
      placements: [
        { colour: "", bounding_box: box(0, 0), artwork: null },
        { colour: "", bounding_box: box(0, 0), artwork: null },
      ],
    });
    expect(screen.getByText(/2 boxes have no colour/)).toBeInTheDocument();
  });

  it("says nothing when every box has a colour", () => {
    renderPanel();
    expect(screen.queryByText(/no colour/)).not.toBeInTheDocument();
  });

  it("selects a box when its row is clicked", () => {
    const { onSelect } = renderPanel();
    fireEvent.click(screen.getByText("2 · black"));
    expect(onSelect).toHaveBeenCalledWith(1);
  });

  describe("the selected box", () => {
    it("offers the colours already used in this workspace, without forcing one", () => {
      renderPanel();
      const input = screen.getByLabelText("Colour") as HTMLInputElement;
      expect(input.getAttribute("list")).toBeTruthy();
      const options = [...document.querySelectorAll("datalist option")].map((o) =>
        o.getAttribute("value"),
      );
      expect(options).toEqual(["sand", "black", "navy"]);
    });

    it("writes a typed colour through", () => {
      const { onChange } = renderPanel();
      fireEvent.change(screen.getByLabelText("Colour"), { target: { value: "moss" } });
      expect(must(onChange.mock.calls[0])[0][0].colour).toBe("moss");
    });

    it("exposes all four corners, since a box is a quad and not a rectangle", () => {
      // render/config.py: BoundingBox is a homography quad on purpose, so
      // angled and draped photos are representable. An x/y/w/h editor would
      // silently discard the skew on every one of them.
      renderPanel();
      for (const corner of [1, 2, 3, 4]) {
        expect(screen.getByLabelText(`Corner ${corner} x`)).toBeInTheDocument();
        expect(screen.getByLabelText(`Corner ${corner} y`)).toBeInTheDocument();
      }
    });

    it("writes an edited corner back to that corner only", () => {
      const { onChange } = renderPanel();
      fireEvent.change(screen.getByLabelText("Corner 2 y"), { target: { value: "17" } });
      const next = must(onChange.mock.calls[0])[0][0].bounding_box;
      expect(next[1]).toEqual({ x: 100, y: 17 });
      expect(next[0]).toEqual({ x: 0, y: 0 });
    });

    it("reports the box's extent, which is what the eye actually checks", () => {
      renderPanel();
      expect(screen.getByText("100 × 80")).toBeInTheDocument();
    });

    it("ignores a corner value that is not a number", () => {
      const { onChange } = renderPanel();
      fireEvent.change(screen.getByLabelText("Corner 1 x"), { target: { value: "abc" } });
      expect(onChange).not.toHaveBeenCalled();
    });
  });

  describe("actions", () => {
    it("adds a box", () => {
      const { onChange, onSelect } = renderPanel();
      fireEvent.click(screen.getByRole("button", { name: "+ Add" }));
      expect(must(onChange.mock.calls[0])[0]).toHaveLength(3);
      expect(onSelect).toHaveBeenCalledWith(2);
    });

    it("duplicates the selected box, offset so it is not hidden underneath", () => {
      const { onChange } = renderPanel();
      fireEvent.click(screen.getByRole("button", { name: "Duplicate" }));
      const next = must(onChange.mock.calls[0])[0];
      expect(next).toHaveLength(3);
      expect(next[1].bounding_box[0].x).toBe(100);
    });

    it("deletes the selected box", () => {
      const { onChange } = renderPanel();
      fireEvent.click(screen.getByRole("button", { name: /Delete/ }));
      expect(must(onChange.mock.calls[0])[0]).toEqual([PLACEMENTS[1]]);
    });

    it("brings the selected box to the front by moving it last", () => {
      // render_scene layers in list order, so "front" is the end of the list.
      // No z-index field is needed, or wanted.
      const { onChange, onSelect } = renderPanel();
      fireEvent.click(screen.getByRole("button", { name: "Bring to front" }));
      const next = must(onChange.mock.calls[0])[0];
      expect(next.map((p: Placement) => p.colour)).toEqual(["black", "sand"]);
      expect(onSelect).toHaveBeenCalledWith(1);
    });
  });
});
