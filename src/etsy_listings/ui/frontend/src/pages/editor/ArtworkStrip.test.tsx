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
  initialOpen = null,
}: {
  design: DesignMap;
  colours: string[];
  onChange: (next: DesignMap, picked: string | null) => void;
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

describe("ArtworkStrip reading a linked pair (interactions §1)", () => {
  it("shows one design for all shirts, mirrored on the dark card", async () => {
    renderStrip({ default: HIKE });
    await screen.findByText("Prints on every colour you sell");

    const all = card("For all shirts");
    expect(all).toHaveTextContent("take-a-hike");
    const dark = card("For dark shirts");
    expect(dark).toHaveClass("design-row--mirrored");
    expect(dark).toHaveTextContent("take-a-hike · linked");
    expect(dark).toHaveTextContent("Same as all shirts");
    expect(screen.getByRole("button", { name: "Unlink" })).toHaveAttribute("aria-pressed", "true");
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

  it("offers a choice when there is no design yet", async () => {
    renderStrip({});
    await screen.findByText("Prints on every colour you sell");
    expect(card("For all shirts")).toHaveTextContent("No design selected");
    expect(
      screen.getByRole("button", { name: /Choose design for all shirts/ }),
    ).toBeInTheDocument();
  });
});

describe("ArtworkStrip reading an unlinked pair", () => {
  it("names each slot's file and the colours it prints on", async () => {
    renderStrip({ "on-light": DARK_INK, "on-dark": LIGHT_INK });
    expect(await screen.findByText("Prints on Ivory and Natural")).toBeInTheDocument();
    expect(card("For light shirts")).toHaveTextContent("take-a-hike-dark-ink");
    expect(card("For dark shirts")).toHaveTextContent("take-a-hike-light-ink");
    expect(card("For dark shirts")).toHaveTextContent("Prints on Black, Moss and Navy");
    expect(screen.getByRole("button", { name: "Link" })).toHaveAttribute("aria-pressed", "false");
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
  it("Unlink puts the current file in both slots", async () => {
    const { onChange } = renderStrip({ default: HIKE, moss: "designs/moss.png" });
    fireEvent.click(await screen.findByRole("button", { name: "Unlink" }));
    expect(onChange).toHaveBeenCalledWith(
      { "on-light": HIKE, "on-dark": HIKE, moss: "designs/moss.png" },
      null,
    );
  });

  it("Unlink on an empty draft records the mode with two nulls", async () => {
    const { onChange } = renderStrip({});
    fireEvent.click(await screen.findByRole("button", { name: "Unlink" }));
    expect(onChange).toHaveBeenCalledWith({ "on-light": null, "on-dark": null }, null);
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
    expect(onChange).toHaveBeenCalledWith(
      { default: "designs/camp-coffee.png" },
      "designs/camp-coffee.png",
    );
    expect(screen.queryByText("Recent designs for all shirts")).not.toBeInTheDocument();
  });

  it("Use a different one splits the pair, light keeping the old file", async () => {
    const { onChange } = renderStrip({ default: HIKE });
    fireEvent.click(
      await screen.findByRole("button", { name: /Use a different design for dark shirts/ }),
    );
    expect(screen.getByText("Recent designs for dark shirts")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /take-a-hike-light-ink/ }));

    expect(onChange).toHaveBeenCalledWith({ "on-light": HIKE, "on-dark": LIGHT_INK }, LIGHT_INK);
  });

  it("picks for one slot of an unlinked pair", async () => {
    const { onChange } = renderStrip({ "on-light": null, "on-dark": LIGHT_INK });
    fireEvent.click(await screen.findByRole("button", { name: /Choose design for light shirts/ }));
    fireEvent.click(screen.getByRole("button", { name: /take-a-hike-dark-ink/ }));
    expect(onChange).toHaveBeenCalledWith({ "on-light": DARK_INK, "on-dark": LIGHT_INK }, DARK_INK);
  });

  it("Link keeps the one distinct file without asking", async () => {
    const { onChange } = renderStrip({ "on-light": null, "on-dark": LIGHT_INK });
    fireEvent.click(await screen.findByRole("button", { name: "Link" }));
    expect(onChange).toHaveBeenCalledWith({ default: LIGHT_INK }, null);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("Link with two files asks which to keep, and Cancel changes nothing", async () => {
    const { onChange } = renderStrip({ "on-light": DARK_INK, "on-dark": LIGHT_INK });
    fireEvent.click(await screen.findByRole("button", { name: "Link" }));

    expect(
      screen.getByRole("dialog", { name: "Which design should every shirt print?" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("Link with two files writes the chosen one as the design for every shirt", async () => {
    const { onChange } = renderStrip({ "on-light": DARK_INK, "on-dark": LIGHT_INK });
    fireEvent.click(await screen.findByRole("button", { name: "Link" }));
    fireEvent.click(screen.getByRole("radio", { name: /take-a-hike-light-ink/ }));
    fireEvent.click(screen.getByRole("button", { name: "Use one design" }));

    expect(onChange).toHaveBeenCalledWith({ default: LIGHT_INK }, null);
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

    expect(onChange).toHaveBeenCalledWith(
      { "on-light": "designs/trail-mix.png", "on-dark": LIGHT_INK },
      "designs/trail-mix.png",
    );
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

  it("is the design for all shirts while linked", async () => {
    renderStrip({ default: HIKE });
    fireEvent.click(await screen.findByRole("button", { name: /Change design for all shirts/ }));
    fireEvent.click(screen.getByRole("button", { name: "Find a design…" }));
    expect(screen.getByRole("dialog", { name: "Design for all shirts" })).toHaveTextContent(
      "Every colour prints it, apart from any with their own design.",
    );
  });
});
