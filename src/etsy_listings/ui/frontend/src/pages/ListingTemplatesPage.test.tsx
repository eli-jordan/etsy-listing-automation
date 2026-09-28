import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import * as batchesApi from "../api/batches";
import * as templatesApi from "../api/listingTemplates";
import type { ListingTemplateSummary } from "../types";
import { ListingTemplatesPage } from "./ListingTemplatesPage";

function card(over: Partial<ListingTemplateSummary> & { name: string }): ListingTemplateSummary {
  return {
    garment: "Comfort Colors 1717",
    colour_count: 5,
    pricing_plan_name: "standard-nok",
    media: [
      { template: "flat-lay-01", colour: "black" },
      "./assets/shots/back.png",
      "common-media/size-guide.png",
      { template: "flat-lay-01", colour: "ivory" },
    ],
    batch_count: 0,
    ...over,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/listing-templates"]}>
      <Routes>
        <Route path="/listing-templates" element={<ListingTemplatesPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function cardFor(name: string): HTMLElement {
  const found = screen.getByText(name).closest("article");
  if (found === null) throw new Error(`no card for ${name}`);
  return found;
}

// Recent batches has its own tests (`RecentBatches.test.tsx`).
beforeEach(() => {
  vi.spyOn(batchesApi, "listBatches").mockResolvedValue([]);
});
afterEach(() => vi.restoreAllMocks());

describe("ListingTemplatesPage", () => {
  it("shows a card per template with what it holds (UI doc §2)", async () => {
    vi.spyOn(templatesApi, "listListingTemplates").mockResolvedValue([
      card({ name: "heavyweight-tee" }),
      card({ name: "trail-hoodie", colour_count: 1, pricing_plan_name: null, batch_count: 2 }),
    ]);
    renderPage();

    await screen.findByText("heavyweight-tee");
    expect(screen.getByText("2 templates")).toBeInTheDocument();
    const first = within(cardFor("heavyweight-tee"));
    expect(first.getByText("Comfort Colors 1717 · 5 colours · standard-nok")).toBeInTheDocument();
    expect(first.getByText("4 gallery images · No batches yet")).toBeInTheDocument();
    const second = within(cardFor("trail-hoodie"));
    expect(
      second.getByText("Comfort Colors 1717 · 1 colour · Prices set per size"),
    ).toBeInTheDocument();
    expect(second.getByText("4 gallery images · Used by 2 batches")).toBeInTheDocument();
  });

  it("draws the first three gallery entries, the template's own files from its directory", async () => {
    vi.spyOn(templatesApi, "listListingTemplates").mockResolvedValue([
      card({ name: "heavyweight-tee" }),
    ]);
    const { container } = renderPage();
    await screen.findByText("heavyweight-tee");

    const sources = [...container.querySelectorAll(".bc-card__gallery img")].map((img) =>
      img.getAttribute("src"),
    );
    expect(sources).toEqual([
      "/api/templates/flat-lay-01/thumbnail?colour=black",
      "/api/listing-templates/heavyweight-tee/media-files/assets/shots/back.png/thumbnail",
      "/api/common-media/size-guide.png/thumbnail",
    ]);
  });

  it("starts a batch from a card with its template chosen, or from the head", async () => {
    vi.spyOn(templatesApi, "listListingTemplates").mockResolvedValue([
      card({ name: "heavyweight-tee" }),
    ]);
    renderPage();
    await screen.findByText("heavyweight-tee");

    expect(screen.getByRole("link", { name: "Start batch" })).toHaveAttribute(
      "href",
      "/batches/new?template=heavyweight-tee",
    );
    expect(screen.getByRole("link", { name: "New batch" })).toHaveAttribute("href", "/batches/new");
  });

  it("deletes a template only once confirmed, and the card goes", async () => {
    vi.spyOn(templatesApi, "listListingTemplates").mockResolvedValue([
      card({ name: "heavyweight-tee" }),
      card({ name: "everyday-tee" }),
    ]);
    const remove = vi.spyOn(templatesApi, "deleteListingTemplate").mockResolvedValue();
    renderPage();
    await screen.findByText("heavyweight-tee");

    fireEvent.click(screen.getByRole("button", { name: "Delete heavyweight-tee" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
    expect(remove).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Delete heavyweight-tee" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/Delete heavyweight-tee\?/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(screen.queryByText("heavyweight-tee")).not.toBeInTheDocument());
    expect(remove).toHaveBeenCalledWith("heavyweight-tee");
    expect(screen.getByText("everyday-tee")).toBeInTheDocument();
    expect(screen.getByText("1 template")).toBeInTheDocument();
  });

  it("says a failed delete, keeping the card", async () => {
    vi.spyOn(templatesApi, "listListingTemplates").mockResolvedValue([
      card({ name: "heavyweight-tee" }),
    ]);
    vi.spyOn(templatesApi, "deleteListingTemplate").mockRejectedValue(new Error("nope"));
    renderPage();
    await screen.findByText("heavyweight-tee");

    fireEvent.click(screen.getByRole("button", { name: "Delete heavyweight-tee" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));

    expect(await screen.findByText("Could not delete heavyweight-tee")).toBeInTheDocument();
    expect(screen.getByText("heavyweight-tee")).toBeInTheDocument();
  });

  it("explains how a template is made, however many there are", async () => {
    vi.spyOn(templatesApi, "listListingTemplates").mockResolvedValue([]);
    renderPage();

    expect(await screen.findByText("0 templates")).toBeInTheDocument();
    expect(
      screen.getByText(/open a finished listing and choose Save as listing template/),
    ).toBeInTheDocument();
  });

  it("says so when the templates cannot be loaded", async () => {
    vi.spyOn(templatesApi, "listListingTemplates").mockRejectedValue(new Error("down"));
    renderPage();

    expect(await screen.findByText("Could not load listing templates")).toBeInTheDocument();
  });

  it("edits and clones from the card, the only places those actions live (UI doc §2)", async () => {
    vi.spyOn(templatesApi, "listListingTemplates").mockResolvedValue([
      card({ name: "heavyweight-tee" }),
    ]);
    renderPage();
    await screen.findByText("heavyweight-tee");

    expect(screen.getByRole("link", { name: "Edit" })).toHaveAttribute(
      "href",
      "/listing-templates/heavyweight-tee",
    );
    // Clone opens the same *name it* state Save as does (UI doc §1).
    expect(screen.getByRole("link", { name: "Clone heavyweight-tee" })).toHaveAttribute(
      "href",
      "/listing-templates/new?from_template=heavyweight-tee",
    );
  });
});

describe("a listing-template card as a drop target (UI doc §2)", () => {
  function pngs(count: number): File[] {
    return Array.from(
      { length: count },
      (_, i) => new File(["png"], `design-${i}.png`, { type: "image/png" }),
    );
  }

  function transfer(files: File[]) {
    return {
      files,
      items: files.map((f) => ({ kind: "file", type: f.type })),
      types: ["Files"],
    };
  }

  function renderRoutes() {
    return render(
      <MemoryRouter initialEntries={["/listing-templates"]}>
        <Routes>
          <Route path="/listing-templates" element={<ListingTemplatesPage />} />
          <Route path="/batches/staging/:id" element={<p>staging review</p>} />
          <Route path="/batches/new" element={<RefusalProbe />} />
        </Routes>
      </MemoryRouter>,
    );
  }

  beforeEach(() => {
    vi.spyOn(templatesApi, "listListingTemplates").mockResolvedValue([
      card({ name: "heavyweight-tee" }),
      card({ name: "trail-hoodie" }),
    ]);
  });

  it("says what a drop will do only while files are over it", async () => {
    renderRoutes();
    await screen.findByText("heavyweight-tee");
    const target = cardFor("heavyweight-tee");

    fireEvent.dragEnter(target, { dataTransfer: transfer(pngs(14)) });

    expect(within(target).getByText("Drop to stage 14 PNGs")).toBeInTheDocument();
    expect(within(target).getByText(/with heavyweight-tee/)).toBeInTheDocument();
    expect(within(cardFor("trail-hoodie")).queryByText(/Drop to stage/)).not.toBeInTheDocument();

    fireEvent.dragLeave(target, { dataTransfer: transfer(pngs(14)) });
    expect(within(target).queryByText(/Drop to stage/)).not.toBeInTheDocument();
  });

  it("names a ZIP being dragged as a ZIP (batch plan PR 7)", async () => {
    renderRoutes();
    await screen.findByText("heavyweight-tee");
    const target = cardFor("heavyweight-tee");
    const zip = new File(["PK"], "kittl-export.zip", { type: "application/zip" });

    fireEvent.dragEnter(target, { dataTransfer: transfer([zip]) });

    expect(within(target).getByText("Drop to stage a ZIP")).toBeInTheDocument();
  });

  it("posts a drop straight to staging with that template, skipping New batch", async () => {
    const stage = vi
      .spyOn(batchesApi, "stageDesigns")
      .mockResolvedValue({ id: "s1" } as batchesApi.StagingDetail);
    renderRoutes();
    await screen.findByText("heavyweight-tee");
    const files = pngs(2);

    fireEvent.drop(cardFor("trail-hoodie"), { dataTransfer: transfer(files) });

    expect(await screen.findByText("staging review")).toBeInTheDocument();
    expect(stage).toHaveBeenCalledWith("trail-hoodie", files);
  });

  it("lands a refused drop on New batch with the template chosen and the refusal shown", async () => {
    vi.spyOn(batchesApi, "stageDesigns").mockRejectedValue(
      new batchesApi.StagingRefused({
        message: "26 designs is more than one batch takes.",
        remedy: "Split them into two batches of at most 25.",
      }),
    );
    renderRoutes();
    await screen.findByText("heavyweight-tee");

    fireEvent.drop(cardFor("heavyweight-tee"), { dataTransfer: transfer(pngs(26)) });

    expect(await screen.findByText("template=heavyweight-tee")).toBeInTheDocument();
    expect(
      screen.getByText("refused: 26 designs is more than one batch takes."),
    ).toBeInTheDocument();
  });
});

function RefusalProbe() {
  const location = useLocation();
  const refused = (location.state as { refused?: { message: string } } | null)?.refused;
  return (
    <>
      <p>{location.search.slice(1)}</p>
      <p>refused: {refused?.message}</p>
    </>
  );
}
