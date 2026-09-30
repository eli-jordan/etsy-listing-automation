import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import * as batchesApi from "../api/batches";
import * as templatesApi from "../api/listingTemplates";
import type { ListingTemplateSummary } from "../types";
import { NewBatchPage } from "./NewBatchPage";

function card(name: string, garment: string, minimum: number): ListingTemplateSummary {
  return {
    name,
    garment,
    colour_count: 5,
    pricing_plan_name: null,
    media: [{ template: "flat-lay-01", colour: "black" }],
    batch_count: 0,
    design_minimum: { width: minimum, height: minimum + 600 },
  };
}

function renderPage(url = "/batches/new") {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/batches/new" element={<NewBatchPage />} />
        <Route path="/batches/staging/:id" element={<p>staging page</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

const png = () => new File(["x"], "Night Hike.png", { type: "image/png" });

afterEach(() => vi.restoreAllMocks());

describe("NewBatchPage", () => {
  it("preselects ?template= and takes the size hint from its garment (UI doc §4)", async () => {
    vi.spyOn(templatesApi, "listListingTemplates").mockResolvedValue([
      card("heavyweight-tee", "Comfort Colors 1717", 3402),
      card("everyday-tee", "Bella + Canvas 3001", 3000),
    ]);
    renderPage("/batches/new?template=everyday-tee");

    const chosen = await screen.findByRole("radio", { name: /everyday-tee/ });
    expect(chosen).toHaveAttribute("aria-checked", "true");
    expect(
      screen.getByText("At least 3000 × 3600 px (90% of the Bella + Canvas 3001 print area)"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: /heavyweight-tee/ }));
    expect(
      screen.getByText("At least 3402 × 4002 px (90% of the Comfort Colors 1717 print area)"),
    ).toBeInTheDocument();
  });

  it("stages dropped files with the chosen template and opens the review", async () => {
    vi.spyOn(templatesApi, "listListingTemplates").mockResolvedValue([
      card("heavyweight-tee", "Comfort Colors 1717", 3402),
    ]);
    const stage = vi
      .spyOn(batchesApi, "stageDesigns")
      .mockResolvedValue({ id: "abc" } as batchesApi.StagingDetail);
    renderPage();
    await screen.findByRole("radio", { name: /heavyweight-tee/ });

    const file = png();
    fireEvent.change(screen.getByLabelText("Design files"), { target: { files: [file] } });

    await screen.findByText("staging page");
    expect(stage).toHaveBeenCalledWith("heavyweight-tee", [file]);
  });

  it("shows a refusal with its remedy and stays on the page", async () => {
    vi.spyOn(templatesApi, "listListingTemplates").mockResolvedValue([
      card("heavyweight-tee", "Comfort Colors 1717", 3402),
    ]);
    vi.spyOn(batchesApi, "stageDesigns").mockRejectedValue(
      new batchesApi.StagingRefused({
        message: "They hold 31 different PNG designs, and a batch takes at most 25.",
        remedy: "Split them into smaller batches. Nothing was uploaded or changed.",
      }),
    );
    renderPage();
    await screen.findByRole("radio", { name: /heavyweight-tee/ });

    fireEvent.drop(screen.getByRole("button", { name: /Drop a ZIP or PNGs here/ }), {
      dataTransfer: { files: [png()] },
    });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Night Hike.png was not staged.");
    expect(alert).toHaveTextContent("They hold 31 different PNG designs");
    expect(alert).toHaveTextContent("Nothing was uploaded or changed.");
    expect(screen.getByText("Drop a different ZIP or PNGs")).toBeInTheDocument();
  });

  it("shows a refusal handed over by a card drop, with that template chosen", async () => {
    /* UI doc, closed question 2: a refused drop on a template card lands
       here with the template preselected and the refusal shown. */
    vi.spyOn(templatesApi, "listListingTemplates").mockResolvedValue([
      card("heavyweight-tee", "Comfort Colors 1717", 3402),
      card("everyday-tee", "Bella + Canvas 3001", 3000),
    ]);
    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: "/batches/new",
            search: "?template=everyday-tee",
            state: {
              refused: {
                message: "26 designs is more than one batch takes.",
                remedy: "Split them into two batches of at most 25.",
                files: ["a.png", "b.png"],
              },
            },
          },
        ]}
      >
        <Routes>
          <Route path="/batches/new" element={<NewBatchPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("radio", { name: /everyday-tee/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    const callout = screen.getByRole("alert");
    expect(callout).toHaveTextContent("These files were not staged.");
    expect(callout).toHaveTextContent("26 designs is more than one batch takes.");
    expect(callout).toHaveTextContent("Split them into two batches of at most 25.");
  });

  it("says any other failure as a page error", async () => {
    vi.spyOn(templatesApi, "listListingTemplates").mockResolvedValue([
      card("heavyweight-tee", "Comfort Colors 1717", 3402),
    ]);
    vi.spyOn(batchesApi, "stageDesigns").mockRejectedValue(new Error("server down"));
    renderPage();
    await screen.findByRole("radio", { name: /heavyweight-tee/ });

    fireEvent.change(screen.getByLabelText("Design files"), { target: { files: [png(), png()] } });

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("server down"));
  });

  it("explains how to make a template when there are none", async () => {
    vi.spyOn(templatesApi, "listListingTemplates").mockResolvedValue([]);
    renderPage();

    expect(await screen.findByText(/There are no listing templates yet/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose files…" })).toBeDisabled();
  });
});
