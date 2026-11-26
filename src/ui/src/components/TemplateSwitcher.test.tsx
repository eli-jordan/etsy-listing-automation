import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { TemplateRename } from "../hooks/useTemplateRename";
import { TemplateSheet, TemplateSwitcher } from "./TemplateSwitcher";

const NAMES = ["alpha", "bravo", "charlie"];

function renderSwitcher(selected: string) {
  const onSelect = vi.fn();
  const onOpen = vi.fn();
  render(
    <TemplateSwitcher
      names={NAMES}
      selected={selected}
      onSelect={onSelect}
      onOpen={onOpen}
      statusChip={<span>calibrated</span>}
      contentsAndSaveState={<span>Colour Matrix · 4 colours</span>}
    />,
  );
  return { onSelect, onOpen };
}

function rename(overrides: Partial<TemplateRename> = {}): TemplateRename {
  return { commit: vi.fn(async () => {}), busy: false, refusal: null, note: null, ...overrides };
}

describe("TemplateSwitcher", () => {
  it("names the open template and where it sits in the catalog", () => {
    renderSwitcher("bravo");
    expect(screen.getByText("bravo")).toBeInTheDocument();
    expect(screen.getByText("2 of 3")).toBeInTheDocument();
    expect(screen.getByText("Colour Matrix · 4 colours")).toBeInTheDocument();
  });

  it("steps to the neighbours with its arrows", () => {
    const { onSelect } = renderSwitcher("bravo");
    fireEvent.click(screen.getByRole("button", { name: "Next template" }));
    fireEvent.click(screen.getByRole("button", { name: "Previous template" }));
    expect(onSelect.mock.calls).toEqual([["charlie"], ["alpha"]]);
  });

  it("disables the arrow that has nowhere to go", () => {
    renderSwitcher("alpha");
    expect(screen.getByRole("button", { name: "Previous template" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next template" })).toBeEnabled();
  });

  it("opens the template list from the name", () => {
    const { onOpen } = renderSwitcher("alpha");
    fireEvent.click(screen.getByRole("button", { name: /Choose another/ }));
    expect(onOpen).toHaveBeenCalledOnce();
  });
});

describe("TemplateSheet", () => {
  it("closes on Escape and from Done", () => {
    const onClose = vi.fn();
    render(
      <TemplateSheet selected="alpha" rename={rename()} onClose={onClose}>
        <p>rail</p>
      </TemplateSheet>,
    );
    expect(screen.getByRole("dialog", { name: "Templates" })).toHaveTextContent("rail");
    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("renames the open template, and leaves an unchanged name alone", () => {
    const commit = vi.fn(async () => {});
    render(
      <TemplateSheet selected="alpha" rename={rename({ commit })} onClose={vi.fn()}>
        <p>rail</p>
      </TemplateSheet>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    fireEvent.click(screen.getByRole("button", { name: "Save name" }));
    expect(commit).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Rename" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    fireEvent.change(screen.getByLabelText("Template name"), { target: { value: " alpha-2 " } });
    fireEvent.click(screen.getByRole("button", { name: "Save name" }));
    expect(commit).toHaveBeenCalledWith("alpha-2");
  });

  it("shows why a name was refused", () => {
    render(
      <TemplateSheet
        selected="alpha"
        rename={rename({ refusal: { name: "taken", message: "Already exists" } })}
        onClose={vi.fn()}
      >
        <p>rail</p>
      </TemplateSheet>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    fireEvent.change(screen.getByLabelText("Template name"), { target: { value: "taken" } });
    expect(screen.getByRole("alert")).toHaveTextContent("Already exists");
  });
});
