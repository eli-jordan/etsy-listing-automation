import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import * as listingsApi from "../api/listings";
import type { ListingSummary } from "../types";
import { DashboardPage } from "./DashboardPage";

function summary(over: Partial<ListingSummary> & { name: string }): ListingSummary {
  return {
    garment_profile: "comfort-colors-1717",
    design: "take-a-hike",
    colour_count: 2,
    status: "draft",
    issue_counts: { block: 0, warn: 0 },
    etsy_listing_id: null,
    printify_product_id: null,
    gestures: [],
    ...over,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/listings/new" element={<p>new-listing page</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

function card(label: string): HTMLElement {
  const el = screen.getByText(label).closest(".stat-card");
  if (el === null) throw new Error(`no stat card for ${label}`);
  return el as HTMLElement;
}

afterEach(() => vi.restoreAllMocks());

describe("DashboardPage", () => {
  it("counts each lifecycle state separately", async () => {
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([
      summary({ name: "a", status: "live" }),
      summary({ name: "b", status: "live" }),
      summary({ name: "c", status: "draft" }),
      summary({ name: "d", status: "deployed" }),
      summary({ name: "e", status: "dirty" }),
    ]);
    renderPage();

    await waitFor(() => expect(within(card("Live")).getByText("2")).toBeInTheDocument());
    expect(within(card("Draft")).getByText("1")).toBeInTheDocument();
    expect(within(card("Deployed")).getByText("1")).toBeInTheDocument();
    expect(within(card("Dirty")).getByText("1")).toBeInTheDocument();
  });

  it("shows zeroes rather than nothing on an empty workspace", async () => {
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([]);
    renderPage();

    await waitFor(() => expect(within(card("Live")).getByText("0")).toBeInTheDocument());
  });

  it("starts a new listing from here too", async () => {
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([]);
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "+ New listing" }));
    await waitFor(() => expect(screen.getByText("new-listing page")).toBeInTheDocument());
  });

  it("reports a failed load rather than showing counts of nothing", async () => {
    vi.spyOn(listingsApi, "listListings").mockRejectedValue(new Error("network"));
    renderPage();

    await waitFor(() => expect(screen.getByText("failed to load listings")).toBeInTheDocument());
    expect(screen.queryByText("Published")).not.toBeInTheDocument();
  });
});
