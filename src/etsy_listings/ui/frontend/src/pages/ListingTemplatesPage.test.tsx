import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
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
});
