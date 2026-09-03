import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { must } from "../test/helpers";
import type { Placement } from "../types";
import { PlacementsPanel } from "./PlacementsPanel";

const BLACK: Placement = {
  colour: "black",
  bounding_box: [
    { x: 0, y: 0 },
    { x: 100, y: 0 },
    { x: 100, y: 100 },
    { x: 0, y: 100 },
  ],
};
const IVORY: Placement = {
  colour: "ivory",
  bounding_box: [
    { x: 200, y: 0 },
    { x: 300, y: 0 },
    { x: 300, y: 100 },
    { x: 200, y: 100 },
  ],
  artwork: "on-dark",
};

describe("PlacementsPanel", () => {
  it("renders one row per placement", () => {
    render(
      <PlacementsPanel
        placements={[BLACK, IVORY]}
        selectedIndex={0}
        onSelect={vi.fn()}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByDisplayValue("black")).toBeInTheDocument();
    expect(screen.getByDisplayValue("ivory")).toBeInTheDocument();
    expect(screen.getByDisplayValue("on-dark")).toBeInTheDocument();
  });

  it("add placement appends one offset from the selected, and selects it", () => {
    const onChange = vi.fn();
    const onSelect = vi.fn();
    render(
      <PlacementsPanel
        placements={[BLACK]}
        selectedIndex={0}
        onSelect={onSelect}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Add placement" }));
    expect(onChange).toHaveBeenCalledTimes(1);
    const [added] = must(onChange.mock.calls[0])[0].slice(-1);
    expect(added.colour).toBe("");
    expect(added.bounding_box[0]).toEqual({ x: 100, y: 0 }); // offset by BLACK's width (100)
    expect(onSelect).toHaveBeenCalledWith(1);
  });

  it("add placement with no existing placements uses a default box", () => {
    const onChange = vi.fn();
    render(
      <PlacementsPanel placements={[]} selectedIndex={0} onSelect={vi.fn()} onChange={onChange} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Add placement" }));
    expect(onChange).toHaveBeenCalledWith([{ colour: "", bounding_box: expect.any(Array) }]);
  });

  it("duplicate & offset inserts a copy right after the selected one", () => {
    const onChange = vi.fn();
    const onSelect = vi.fn();
    render(
      <PlacementsPanel
        placements={[BLACK, IVORY]}
        selectedIndex={0}
        onSelect={onSelect}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Duplicate & offset/ }));
    const next = must(onChange.mock.calls[0])[0];
    expect(next).toHaveLength(3);
    expect(next[1].colour).toBe("black");
    expect(next[1].bounding_box[0]).toEqual({ x: 100, y: 0 });
    expect(onSelect).toHaveBeenCalledWith(1);
  });

  it("duplicate is a no-op when nothing is selected", () => {
    const onChange = vi.fn();
    render(
      <PlacementsPanel placements={[]} selectedIndex={0} onSelect={vi.fn()} onChange={onChange} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Duplicate & offset/ }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("delete selected removes it and selects the previous one", () => {
    const onChange = vi.fn();
    const onSelect = vi.fn();
    render(
      <PlacementsPanel
        placements={[BLACK, IVORY]}
        selectedIndex={1}
        onSelect={onSelect}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Delete selected" }));
    expect(onChange).toHaveBeenCalledWith([BLACK]);
    expect(onSelect).toHaveBeenCalledWith(0);
  });

  it("editing a colour field updates just that placement", () => {
    const onChange = vi.fn();
    render(
      <PlacementsPanel
        placements={[BLACK, IVORY]}
        selectedIndex={0}
        onSelect={vi.fn()}
        onChange={onChange}
      />,
    );
    fireEvent.change(screen.getByDisplayValue("black"), { target: { value: "moss" } });
    const next = must(onChange.mock.calls[0])[0];
    expect(must(next[0]).colour).toBe("moss");
    expect(next[1]).toEqual(IVORY);
  });

  it("clearing the artwork field sets it back to null", () => {
    const onChange = vi.fn();
    render(
      <PlacementsPanel
        placements={[IVORY]}
        selectedIndex={0}
        onSelect={vi.fn()}
        onChange={onChange}
      />,
    );
    fireEvent.change(screen.getByDisplayValue("on-dark"), { target: { value: "" } });
    expect(must(must(onChange.mock.calls[0])[0][0]).artwork).toBeNull();
  });

  it("clicking a row selects it", () => {
    const onSelect = vi.fn();
    render(
      <PlacementsPanel
        placements={[BLACK, IVORY]}
        selectedIndex={0}
        onSelect={onSelect}
        onChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByDisplayValue("ivory").closest("li") as HTMLElement);
    expect(onSelect).toHaveBeenCalledWith(1);
  });
});
