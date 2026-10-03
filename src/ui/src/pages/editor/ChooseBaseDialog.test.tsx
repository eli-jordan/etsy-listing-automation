import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ChooseBaseDialog } from "./ChooseBaseDialog";

const LIGHT = "designs/take-a-hike-dark-ink.png";
const DARK = "designs/take-a-hike-light-ink.png";

function renderDialog(own: string[] = []) {
  const onKeep = vi.fn();
  const onCancel = vi.fn();
  render(
    <ChooseBaseDialog light={LIGHT} dark={DARK} own={own} onKeep={onKeep} onCancel={onCancel} />,
  );
  return { onKeep, onCancel };
}

/** Interactions §5: linking a pair of two files asks which one every shirt
 * prints, and nothing is written until one is chosen. */
describe("ChooseBaseDialog", () => {
  it("offers both files as a radio group, captioned by the slot they fill now", () => {
    renderDialog();
    expect(
      screen.getByRole("dialog", { name: "Which design should every shirt print?" }),
    ).toBeInTheDocument();
    const group = screen.getByRole("radiogroup", { name: "Design to keep" });
    const [light, dark] = screen.getAllByRole("radio");
    expect(group).toContainElement(light ?? null);
    expect(light).toHaveTextContent("take-a-hike-dark-ink");
    expect(light).toHaveTextContent("Now the design for light shirts");
    expect(dark).toHaveTextContent("take-a-hike-light-ink");
    expect(dark).toHaveTextContent("Now the design for dark shirts");
    expect(light).toHaveAttribute("aria-checked", "false");
  });

  it("keeps Use one design disabled until a file is chosen", () => {
    const { onKeep } = renderDialog();
    const confirm = screen.getByRole("button", { name: "Use one design" });
    expect(confirm).toBeDisabled();

    fireEvent.click(screen.getByRole("radio", { name: /take-a-hike-light-ink/ }));

    expect(screen.getByRole("radio", { name: /take-a-hike-light-ink/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    expect(onKeep).toHaveBeenCalledWith(DARK);
  });

  it("changes nothing on Cancel or Escape", () => {
    const { onKeep, onCancel } = renderDialog();
    fireEvent.click(screen.getByRole("radio", { name: /take-a-hike-dark-ink/ }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(2);
    expect(onKeep).not.toHaveBeenCalled();
  });

  it("says colours with their own design keep it, to answer the obvious worry", () => {
    renderDialog(["moss"]);
    expect(screen.getByText("Moss keeps its own design.")).toBeInTheDocument();
  });

  it("says it in the plural for more than one colour", () => {
    renderDialog(["moss", "navy"]);
    expect(screen.getByText("Moss and Navy keep their own design.")).toBeInTheDocument();
  });

  it("says nothing about own designs when there are none", () => {
    renderDialog();
    expect(screen.queryByText(/own design/)).toBeNull();
  });
});
