import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LabelsBar } from "./LabelsBar";

const CAP = "Templates hold up to 10 labels";

function bar(over: Partial<Parameters<typeof LabelsBar>[0]> = {}) {
  const onChange = vi.fn();
  render(
    <LabelsBar saved={[]} draft={[]} known={[]} failure={null} onChange={onChange} {...over} />,
  );
  return onChange;
}

function openField(): HTMLElement {
  fireEvent.click(screen.getByRole("button", { name: "Add label" }));
  return screen.getByRole("textbox", { name: "Add a label" });
}

function type(text: string): HTMLElement {
  const field = openField();
  fireEvent.change(field, { target: { value: text } });
  return field;
}

function options(): string[] {
  return screen.queryAllByRole("option").map((option) => (option.textContent ?? "").trim());
}

describe("LabelsBar", () => {
  it("shows what is saved, not the draft", () => {
    bar({ saved: ["cosy"], draft: ["warm"] });

    expect(screen.getByText("cosy")).toBeInTheDocument();
    expect(screen.queryByText("warm")).not.toBeInTheDocument();
  });

  it("shows a hand-edited label as written", () => {
    bar({ saved: ["Christmas!"], draft: ["Christmas!"] });

    expect(screen.getByText("Christmas!")).toBeInTheDocument();
  });

  it("removes a label from the draft, keeping edits still waiting to save", () => {
    const onChange = bar({ saved: ["cosy", "warm"], draft: ["cosy", "warm", "new"] });

    fireEvent.click(screen.getByRole("button", { name: "Remove cosy" }));

    expect(onChange).toHaveBeenCalledWith(["warm", "new"]);
  });

  describe("adding a label", () => {
    it("suggests labels the template does not hold, at most six", () => {
      const known = ["a1", "a2", "a3", "a4", "a5", "a6", "a7", "held", "Pending"];
      bar({ saved: ["held"], draft: ["held", "pending"], known });

      openField();

      expect(options()).toEqual(["a1", "a2", "a3", "a4", "a5", "a6"]);
    });

    it("offers a hand-edited label as it would save, and only if it could", () => {
      bar({ known: ["Theme:Xmas", "theme:xmas", "oops!"] });

      openField();

      expect(options()).toEqual(["theme:xmas"]);
    });

    it("narrows suggestions to the typed text and offers Create", () => {
      bar({ known: ["cosy", "warm"] });

      type("cos");

      expect(options()).toEqual(["cosy", "Create “cos”"]);
    });

    it("adds the first suggestion on Enter", () => {
      const onChange = bar({ saved: ["warm"], draft: ["warm"], known: ["cosy"] });

      fireEvent.keyDown(type("cos"), { key: "Enter" });

      expect(onChange).toHaveBeenCalledWith(["warm", "cosy"]);
    });

    it("creates the tidied text on Enter when nothing is suggested", () => {
      const onChange = bar();

      fireEvent.keyDown(type("  Road   Trip "), { key: "Enter" });

      expect(onChange).toHaveBeenCalledWith(["road trip"]);
    });

    it("creates the text when Create is clicked, over a suggestion", () => {
      const onChange = bar({ known: ["cosy"] });

      type("cos");
      fireEvent.click(screen.getByRole("option", { name: "Create “cos”" }));

      expect(onChange).toHaveBeenCalledWith(["cos"]);
    });

    it("adds a suggestion when it is clicked", () => {
      const onChange = bar({ known: ["cosy"] });

      openField();
      fireEvent.click(screen.getByRole("option", { name: "cosy" }));

      expect(onChange).toHaveBeenCalledWith(["cosy"]);
    });

    it("closes the field after adding and hands focus back to Add label", () => {
      bar();

      // Unprevented, the same press would go on to click the button focus just
      // moved to, and open the field again.
      const unhandled = fireEvent.keyDown(type("cosy"), { key: "Enter" });

      expect(unhandled).toBe(false);
      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Add label" })).toHaveFocus();
    });

    it("does nothing on Enter with no text", () => {
      const onChange = bar({ known: ["cosy"] });

      fireEvent.keyDown(openField(), { key: "Enter" });

      expect(onChange).not.toHaveBeenCalled();
    });

    it("closes on Escape, drops the text and tells nothing else to cancel", () => {
      const onChange = bar();

      const unhandled = fireEvent.keyDown(type("cosy"), { key: "Escape" });

      expect(unhandled).toBe(false);
      expect(onChange).not.toHaveBeenCalled();
      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Add label" })).toHaveFocus();
      expect(openField()).toHaveValue("");
    });

    it("offers no Create for a label the template already holds", () => {
      const onChange = bar({ saved: ["cosy"], draft: ["cosy"] });

      const field = type("Cosy");
      fireEvent.keyDown(field, { key: "Enter" });

      expect(options()).toEqual([]);
      expect(onChange).not.toHaveBeenCalled();
    });

    it.each([
      ["xmas!", "Letters, numbers, spaces, hyphens and colons only"],
      ["a".repeat(31), "Labels can be up to 30 characters"],
      ["a:b:c", "Use one colon with text on both sides, like theme:christmas"],
    ])("explains why %s cannot save, keeps it, and ignores Enter", (text, reason) => {
      const onChange = bar();

      const field = type(text);
      fireEvent.keyDown(field, { key: "Enter" });

      expect(screen.getByText(reason)).toBeInTheDocument();
      expect(options()).toEqual([]);
      expect(field).toHaveValue(text);
      expect(onChange).not.toHaveBeenCalled();
    });
  });

  describe("at the limit", () => {
    const ten = Array.from({ length: 10 }, (_, i) => `label ${i}`);

    it("disables Add label and says why without hovering", () => {
      bar({ saved: ten, draft: ten });

      const add = screen.getByRole("button", { name: "Add label" });
      expect(add).toBeDisabled();
      expect(add).toHaveAttribute("title", CAP);
      expect(screen.getByText(CAP)).toBeInTheDocument();
    });

    it("counts edits still waiting to save", () => {
      bar({ saved: ten.slice(1), draft: ten });

      expect(screen.getByRole("button", { name: "Add label" })).toBeDisabled();
    });

    it("gives the way back once a label goes", () => {
      bar({ saved: ten, draft: ten.slice(1) });

      expect(screen.getByRole("button", { name: "Add label" })).toBeEnabled();
      expect(screen.queryByText(CAP)).not.toBeInTheDocument();
    });
  });

  it("shows a failed save beside the bar", () => {
    bar({ saved: ["cosy"], draft: ["cosy", "warm"], failure: "could not save template.yaml" });

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("could not save template.yaml");
    expect(within(screen.getByRole("group", { name: "Labels" })).getByRole("alert")).toBe(alert);
  });
});
