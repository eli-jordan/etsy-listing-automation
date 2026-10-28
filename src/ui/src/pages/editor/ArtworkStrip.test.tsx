import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as listingsApi from "../../api/listings";
import type { DesignMap } from "../../types";
import { ArtworkStrip } from "./ArtworkStrip";
import type { SlotTarget } from "./artwork";

const HIKE = "designs/take-a-hike.png";
const DARK_INK = "designs/take-a-hike-dark-ink.png";
const LIGHT_INK = "designs/take-a-hike-light-ink.png";

const DESIGNS = [
  { name: "take-a-hike", file: HIKE },
  { name: "take-a-hike-dark-ink", file: DARK_INK },
  { name: "take-a-hike-light-ink", file: LIGHT_INK },
  { name: "camp-coffee", file: "designs/camp-coffee.png" },
  { name: "trail-mix", file: "designs/trail-mix.png" },
];

const PROFILE = {
  name: "bella-canvas-3001",
  sizes: ["S"],
  colors: {
    black: "dark",
    ivory: "light",
    moss: "dark",
    natural: "light",
    navy: "dark",
  } as Record<string, "light" | "dark">,
};

beforeEach(() => {
  vi.spyOn(listingsApi, "listListingDesigns").mockResolvedValue(DESIGNS);
  vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue([PROFILE]);
});

afterEach(() => vi.restoreAllMocks());

/** The strip with its open panel held the way `ListingEditorShell` holds it. */
function Harness({
  design,
  colours,
  onChange,
  onPreview = () => undefined,
  initialOpen = null,
}: {
  design: DesignMap;
  colours: string[];
  onChange: (next: DesignMap) => void;
  onPreview?: (colour: string) => void;
  initialOpen?: SlotTarget | null;
}) {
  const [open, setOpen] = useState<SlotTarget | null>(initialOpen);
  return (
    <ArtworkStrip
      design={design}
      colours={colours}
      garmentProfile="bella-canvas-3001"
      open={open}
      onOpen={setOpen}
      onChange={onChange}
      onPreview={onPreview}
    />
  );
}

const ALL = ["black", "ivory", "moss", "natural", "navy"];

function renderStrip(design: DesignMap, colours = ALL, initialOpen: SlotTarget | null = null) {
  const onChange = vi.fn();
  const view = render(
    <Harness design={design} colours={colours} onChange={onChange} initialOpen={initialOpen} />,
  );
  return { ...view, onChange };
}

function card(title: string): HTMLElement {
  const el = screen.getByText(title).closest(".design-row");
  if (el === null) throw new Error(`no card titled ${title}`);
  return el as HTMLElement;
}

const SPLIT = "Use different designs on light & dark shirts";
const JOIN = "Use one design for all shirts";

describe("ArtworkStrip reading one design", () => {
  it("shows one selector for all shirts, and no separate dark-shirt selector", async () => {
    renderStrip({ default: HIKE });
    await screen.findByText("Prints on every colour you sell");

    expect(card("For all shirts")).toHaveTextContent("take-a-hike");
    expect(screen.queryByText("For dark shirts")).not.toBeInTheDocument();
    expect(screen.queryByText("For light shirts")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: SPLIT })).toBeInTheDocument();
  });

  it("says when some colours print their own design", async () => {
    renderStrip({ default: HIKE, moss: "designs/moss.png" });
    expect(
      await screen.findByText("Prints on every colour without its own design"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Also printing their own design:/)).toHaveTextContent(
      "Also printing their own design: Moss",
    );
  });

  it("previews a colour with its own design when its name is pressed", async () => {
    const onPreview = vi.fn();
    render(
      <Harness
        design={{ default: HIKE, moss: "designs/moss.png", navy: "designs/navy.png" }}
        colours={ALL}
        onChange={vi.fn()}
        onPreview={onPreview}
      />,
    );
    const line = await screen.findByText(/Also printing their own design:/);
    expect(line).toHaveTextContent("Also printing their own design: Moss, Navy");
    fireEvent.click(within(line).getByRole("button", { name: "Moss" }));
    expect(onPreview).toHaveBeenCalledWith("moss");
  });

  it("notes, when linking two files, which colours keep their own design", async () => {
    renderStrip({ "on-light": DARK_INK, "on-dark": LIGHT_INK, moss: "designs/moss.png" });
    fireEvent.click(await screen.findByRole("button", { name: JOIN }));
    expect(
      screen.getByRole("dialog", { name: "Which design should every shirt print?" }),
    ).toHaveTextContent("Moss keeps its own design.");
  });

  it("offers a choice when there is no design yet", async () => {
    renderStrip({});
    await screen.findByText("Prints on every colour you sell");
    expect(card("For all shirts")).toHaveTextContent("No design selected");
    expect(
      screen.getByRole("button", { name: /Choose design for all shirts/ }),
    ).toBeInTheDocument();
  });
});

describe("ArtworkStrip reading light and dark designs", () => {
  it("names each slot's file and the colours it prints on", async () => {
    renderStrip({ "on-light": DARK_INK, "on-dark": LIGHT_INK });
    expect(await screen.findByText("Prints on Ivory and Natural")).toBeInTheDocument();
    expect(card("For light shirts")).toHaveTextContent("take-a-hike-dark-ink");
    expect(card("For dark shirts")).toHaveTextContent("take-a-hike-light-ink");
    expect(card("For dark shirts")).toHaveTextContent("Prints on Black, Moss and Navy");
    expect(screen.getByRole("button", { name: JOIN })).toBeInTheDocument();
  });

  it("marks an empty slot a colour needs as missing", async () => {
    renderStrip({ "on-light": null, "on-dark": LIGHT_INK });
    await screen.findByText("Prints on Ivory and Natural");
    const light = card("For light shirts");
    expect(light).toHaveClass("design-row--missing");
    expect(light).toHaveTextContent("Choose the design for light shirts");
    expect(
      within(light).getByRole("button", { name: /Choose design for light shirts/ }),
    ).toBeInTheDocument();
  });

  it("says a slot no colour needs is not used", async () => {
    renderStrip({ "on-light": null, "on-dark": LIGHT_INK }, ["black", "navy"]);
    const light = card("For light shirts");
    expect(
      await within(light).findByText("Not used — no colour you sell needs it"),
    ).toBeInTheDocument();
    expect(light).not.toHaveClass("design-row--missing");
  });
});

describe("ArtworkStrip's §3 transitions", () => {
  it("splitting puts the current file in both slots", async () => {
    const { onChange } = renderStrip({ default: HIKE, moss: "designs/moss.png" });
    fireEvent.click(await screen.findByRole("button", { name: SPLIT }));
    expect(onChange).toHaveBeenCalledWith({
      "on-light": HIKE,
      "on-dark": HIKE,
      moss: "designs/moss.png",
    });
  });

  it("splitting an empty draft records the mode with two nulls", async () => {
    const { onChange } = renderStrip({});
    fireEvent.click(await screen.findByRole("button", { name: SPLIT }));
    expect(onChange).toHaveBeenCalledWith({ "on-light": null, "on-dark": null });
  });

  it("changes the design for all shirts from the Recent designs panel", async () => {
    const { onChange } = renderStrip({ default: HIKE });
    fireEvent.click(await screen.findByRole("button", { name: /Change design for all shirts/ }));

    expect(screen.getByText("Recent designs for all shirts")).toBeInTheDocument();
    const recent = screen.getByText("Recent designs for all shirts").closest(".add-panel");
    expect(
      within(recent as HTMLElement).getAllByRole("button", { name: /designs\// }),
    ).toHaveLength(4);
    expect(
      within(recent as HTMLElement).getByRole("button", {
        name: /take-a-hike\b.*designs\/take-a-hike\.png/,
      }),
    ).toHaveClass("template-card--active");

    fireEvent.click(screen.getByRole("button", { name: /camp-coffee/ }));
    expect(onChange).toHaveBeenCalledWith({ default: "designs/camp-coffee.png" });
    expect(screen.queryByText("Recent designs for all shirts")).not.toBeInTheDocument();
  });

  it("a dark-shirt pick asked for elsewhere splits, light keeping the old file", async () => {
    const { onChange } = renderStrip({ default: HIKE }, ALL, { kind: "slot", tone: "dark" });
    expect(await screen.findByText("Recent designs for dark shirts")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /take-a-hike-light-ink/ }));

    expect(onChange).toHaveBeenCalledWith({ "on-light": HIKE, "on-dark": LIGHT_INK });
  });

  it("picks for one slot of a light and dark pair", async () => {
    const { onChange } = renderStrip({ "on-light": null, "on-dark": LIGHT_INK });
    fireEvent.click(await screen.findByRole("button", { name: /Choose design for light shirts/ }));
    fireEvent.click(screen.getByRole("button", { name: /take-a-hike-dark-ink/ }));
    expect(onChange).toHaveBeenCalledWith({ "on-light": DARK_INK, "on-dark": LIGHT_INK });
  });

  it("going back to one design keeps the one distinct file without asking", async () => {
    const { onChange } = renderStrip({ "on-light": null, "on-dark": LIGHT_INK });
    fireEvent.click(await screen.findByRole("button", { name: JOIN }));
    expect(onChange).toHaveBeenCalledWith({ default: LIGHT_INK });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("going back to one design with two files asks which to keep, and Cancel changes nothing", async () => {
    const { onChange } = renderStrip({ "on-light": DARK_INK, "on-dark": LIGHT_INK });
    fireEvent.click(await screen.findByRole("button", { name: JOIN }));

    expect(
      screen.getByRole("dialog", { name: "Which design should every shirt print?" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("going back to one design with two files writes the chosen one", async () => {
    const { onChange } = renderStrip({ "on-light": DARK_INK, "on-dark": LIGHT_INK });
    fireEvent.click(await screen.findByRole("button", { name: JOIN }));
    fireEvent.click(screen.getByRole("radio", { name: /take-a-hike-light-ink/ }));
    fireEvent.click(screen.getByRole("button", { name: "Use one design" }));

    expect(onChange).toHaveBeenCalledWith({ default: LIGHT_INK });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens the panel another part of the editor asked for", async () => {
    renderStrip({ "on-light": null, "on-dark": LIGHT_INK }, ALL, { kind: "slot", tone: "light" });
    expect(await screen.findByText("Recent designs for light shirts")).toBeInTheDocument();
    expect(card("For light shirts")).toHaveClass("design-row--open");
  });
});

describe("ArtworkStrip's full design list (interactions §4)", () => {
  it("is titled for the slot, hints who prints it and marks the current file", async () => {
    const { onChange } = renderStrip({ "on-light": DARK_INK, "on-dark": LIGHT_INK });
    fireEvent.click(await screen.findByRole("button", { name: /Change design for light shirts/ }));
    fireEvent.click(screen.getByRole("button", { name: "Find a design…" }));

    const dialog = screen.getByRole("dialog", { name: "Design for light shirts" });
    expect(dialog).toHaveTextContent("Prints on Ivory and Natural.");
    const current = within(dialog).getByRole("button", { name: /take-a-hike-dark-ink/ });
    expect(current).toHaveTextContent("Current");

    fireEvent.change(within(dialog).getByPlaceholderText("Search your designs…"), {
      target: { value: "TRAIL" },
    });
    expect(within(dialog).queryByRole("button", { name: /camp-coffee/ })).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: /trail-mix/ }));

    expect(onChange).toHaveBeenCalledWith({
      "on-light": "designs/trail-mix.png",
      "on-dark": LIGHT_INK,
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("says so when no colour uses the slot, and when nothing matches", async () => {
    renderStrip({ "on-light": null, "on-dark": LIGHT_INK }, ["black"]);
    fireEvent.click(await screen.findByRole("button", { name: /Choose design for light shirts/ }));
    fireEvent.click(screen.getByRole("button", { name: "Find a design…" }));

    const dialog = screen.getByRole("dialog", { name: "Design for light shirts" });
    expect(dialog).toHaveTextContent("No colour you sell uses it right now.");
    fireEvent.change(within(dialog).getByPlaceholderText("Search your designs…"), {
      target: { value: "zzz" },
    });
    expect(within(dialog).getByText("No designs match your search")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("is the design for all shirts on one design", async () => {
    renderStrip({ default: HIKE });
    fireEvent.click(await screen.findByRole("button", { name: /Change design for all shirts/ }));
    fireEvent.click(screen.getByRole("button", { name: "Find a design…" }));
    expect(screen.getByRole("dialog", { name: "Design for all shirts" })).toHaveTextContent(
      "Every colour prints it, apart from any with their own design.",
    );
  });
});

const png = (name: string) =>
  new File([new Uint8Array([137, 80, 78, 71])], name, { type: "image/png" });

/** A file dragged over `el` and dropped on it, as the browser fires it. */
function drop(el: HTMLElement, file: File) {
  const dataTransfer = { files: [file], types: ["Files"] };
  fireEvent.dragEnter(el, { dataTransfer });
  fireEvent.dragOver(el, { dataTransfer });
  fireEvent.drop(el, { dataTransfer });
}

describe("ArtworkStrip taking a dropped file", () => {
  it("uploads a file dropped on the one design and picks it for all shirts", async () => {
    const upload = vi
      .spyOn(listingsApi, "uploadListingDesign")
      .mockResolvedValue({ name: "sunset", file: "designs/sunset.png" });
    const { onChange } = renderStrip({ default: HIKE, moss: "designs/moss.png" });
    await screen.findByText("Prints on every colour without its own design");

    drop(card("For all shirts"), png("sunset.png"));

    expect(upload).toHaveBeenCalledWith(expect.objectContaining({ name: "sunset.png" }));
    await vi.waitFor(() =>
      expect(onChange).toHaveBeenCalledWith({
        default: "designs/sunset.png",
        moss: "designs/moss.png",
      }),
    );
  });

  it("drops onto one tone of a light and dark pair without touching the other", async () => {
    vi.spyOn(listingsApi, "uploadListingDesign").mockResolvedValue({
      name: "night-ink",
      file: "designs/night-ink.png",
    });
    const { onChange } = renderStrip({ "on-light": DARK_INK, "on-dark": LIGHT_INK });
    await screen.findByText("Prints on Ivory and Natural");

    drop(card("For dark shirts"), png("night-ink.png"));

    await vi.waitFor(() =>
      expect(onChange).toHaveBeenCalledWith({
        "on-light": DARK_INK,
        "on-dark": "designs/night-ink.png",
      }),
    );
  });

  it("offers only the selectors on show as targets, so a drop never splits", async () => {
    renderStrip({ default: HIKE });
    await screen.findByText("Prints on every colour you sell");
    const all = card("For all shirts");

    fireEvent.dragEnter(all, { dataTransfer: { files: [], types: ["Files"] } });

    expect(document.querySelectorAll(".design-row--target")).toHaveLength(1);
    expect(all).toHaveTextContent("Drop to upload and use on all shirts");
    expect(
      screen.queryByText(/Drop to upload and use on (light|dark) shirts/),
    ).not.toBeInTheDocument();
  });

  it("says why an upload was refused and leaves the design alone", async () => {
    vi.spyOn(listingsApi, "uploadListingDesign").mockRejectedValue(
      new listingsApi.ListingsApiError("designs must be PNG files, and photo.jpg is a JPEG image"),
    );
    const { onChange } = renderStrip({ default: HIKE });
    await screen.findByText("Prints on every colour you sell");

    drop(card("For all shirts"), png("photo.jpg"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't upload photo.jpg: designs must be PNG files, and photo.jpg is a JPEG image",
    );
    expect(onChange).not.toHaveBeenCalled();
  });

  it("uploads from the Recent designs panel for the slot it is open for", async () => {
    vi.spyOn(listingsApi, "uploadListingDesign").mockResolvedValue({
      name: "sunset",
      file: "designs/sunset.png",
    });
    const { onChange } = renderStrip({ "on-light": DARK_INK, "on-dark": LIGHT_INK });
    fireEvent.click(await screen.findByRole("button", { name: /Change design for light shirts/ }));

    fireEvent.change(screen.getByLabelText("Upload a PNG…"), {
      target: { files: [png("sunset.png")] },
    });

    await vi.waitFor(() =>
      expect(onChange).toHaveBeenCalledWith({
        "on-light": "designs/sunset.png",
        "on-dark": LIGHT_INK,
      }),
    );
  });
});
