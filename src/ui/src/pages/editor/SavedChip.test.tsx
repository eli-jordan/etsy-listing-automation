import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { onPhone } from "../../test/touch";
import { SavedChip } from "./SavedChip";

afterEach(() => vi.unstubAllGlobals());

function openChip() {
  render(
    <SavedChip path="listings/take-a-hike/listing.yaml" savedAt={Date.now()} subject="listing" />,
  );
  const trigger = screen.getByTitle("Where this is saved");
  fireEvent.click(trigger);
  return trigger;
}

describe("SavedChip's Copy", () => {
  it("says Copied once the clipboard has taken the path", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    openChip();

    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Copy" })));

    expect(writeText).toHaveBeenCalledWith("listings/take-a-hike/listing.yaml");
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("claims nothing on a page with no clipboard access, such as an insecure origin", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: undefined });
    openChip();

    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Copy" })));

    expect(screen.getByRole("button", { name: "Copy" })).toBeInTheDocument();
  });
});

describe("SavedChip on a phone", () => {
  it("stays open when Copy in its sheet is pressed", () => {
    onPhone();
    openChip();

    fireEvent.mouseDown(screen.getByRole("button", { name: "Copy" }));

    expect(screen.getByRole("dialog", { name: "Listing file" })).toBeInTheDocument();
  });

  it("says it opens a dialog rather than pointing at an id the sheet does not have", () => {
    onPhone();
    const trigger = openChip();

    expect(trigger).toHaveAttribute("aria-haspopup", "dialog");
    expect(trigger).not.toHaveAttribute("aria-controls");
  });

  it("points at its card on a desktop", () => {
    const trigger = openChip();

    expect(trigger).toHaveAttribute("aria-controls", screen.getByRole("dialog").id);
  });
});
