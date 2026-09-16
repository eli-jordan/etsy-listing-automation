import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import * as listingsApi from "../api/listings";
import type { ListingSummary } from "../types";
import { ListingsPage } from "./ListingsPage";

function EditorStub() {
  const { name } = useParams();
  return <p>editor for {name}</p>;
}

function summary(over: Partial<ListingSummary> & { name: string }): ListingSummary {
  return {
    garment_profile: "comfort-colors-1717",
    design: "take-a-hike",
    colour_count: 2,
    status: "draft",
    issue_counts: { block: 0, warn: 0 },
    ...over,
  };
}

/* A listing's name appears twice in its row -- once as the link, once inside
   the hover card -- so every query for "the row for X" goes through the link,
   which is unique and is the affordance a user actually clicks. */
const findRowLink = (name: string) => screen.findByRole("button", { name });
const queryRowLink = (name: string) => screen.queryByRole("button", { name });

function rowFor(name: string): HTMLElement {
  const row = screen.getByRole("button", { name }).closest("tr");
  if (row === null) throw new Error(`no row for ${name}`);
  return row;
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/listings"]}>
      <Routes>
        <Route path="/listings" element={<ListingsPage />} />
        <Route path="/listings/new" element={<p>new-listing page</p>} />
        <Route path="/listings/:name" element={<EditorStub />} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ListingsPage", () => {
  it("lists every listing with its garment and status", async () => {
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([
      summary({ name: "take-a-hike", status: "draft" }),
      summary({ name: "wildflower-crew", status: "live" }),
    ]);

    renderPage();

    await findRowLink("take-a-hike");
    expect(await findRowLink("wildflower-crew")).toBeInTheDocument();
    expect(screen.getAllByText("comfort-colors-1717").length).toBeGreaterThan(0);
  });

  it("shows the listing's own artwork on its row", async () => {
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([
      summary({ name: "take-a-hike", design: "mountain-sunset" }),
    ]);
    renderPage();
    await findRowLink("take-a-hike");

    // Queried by tag, not by role: the thumbnail is decorative (`alt=""`,
    // the row's name is right beside it), so it deliberately has no role.
    expect(rowFor("take-a-hike").querySelector("img")).toHaveAttribute(
      "src",
      "/api/listing-designs/mountain-sunset/thumbnail",
    );
  });

  it("falls back to a placeholder when no single design stands for the listing", async () => {
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([
      summary({ name: "two-inks", design: null }),
    ]);
    renderPage();
    await findRowLink("two-inks");

    expect(rowFor("two-inks").querySelector("img")).toBeNull();
  });

  it("carries a detail card with what the row itself has no column for", async () => {
    /* Revealed on hover by CSS alone (no JS state), so what is asserted here
       is that the card's *content* is on the row -- the artwork, the garment
       and the colour count the table has no column for. That it appears on
       hover is a CSS rule, checked in the browser layer. */
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([
      summary({ name: "take-a-hike", colour_count: 4, status: "live" }),
    ]);
    renderPage();
    await findRowLink("take-a-hike");

    const card = rowFor("take-a-hike").querySelector(".listing-popup");
    expect(card).not.toBeNull();
    expect(within(card as HTMLElement).getByText("4 colours")).toBeInTheDocument();
    expect(within(card as HTMLElement).getByText("comfort-colors-1717")).toBeInTheDocument();
    expect(within(card as HTMLElement).getByText("Live")).toBeInTheDocument();
  });

  it("says «1 colour» rather than «1 colours» on a single-colour listing", async () => {
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([
      summary({ name: "mono", colour_count: 1 }),
    ]);
    renderPage();
    await findRowLink("mono");

    const card = rowFor("mono").querySelector(".listing-popup");
    expect(within(card as HTMLElement).getByText("1 colour")).toBeInTheDocument();
  });

  it("links a row's open-on menu at the listing and product themselves", async () => {
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([
      summary({
        name: "live-one",
        status: "live",
        etsy_listing_id: 4572960161,
        printify_product_id: "6aa332559f8d2ff30103b4c9",
      }),
    ]);
    renderPage();
    await findRowLink("live-one");

    fireEvent.click(
      within(rowFor("live-one")).getByRole("button", { name: "Open on Etsy or Printify" }),
    );

    expect(within(rowFor("live-one")).getByRole("link", { name: /Open on Etsy/ })).toHaveAttribute(
      "href",
      "https://www.etsy.com/your/shops/me/listing-editor/edit/4572960161",
    );
    expect(
      within(rowFor("live-one")).getByRole("link", { name: /Open on Printify/ }),
    ).toHaveAttribute("href", "https://printify.com/app/product-details/6aa332559f8d2ff30103b4c9");
  });

  it("closes the open-on menu when clicking away", async () => {
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([
      summary({ name: "live-one", status: "live", etsy_listing_id: 555 }),
    ]);
    renderPage();
    await findRowLink("live-one");

    fireEvent.click(
      within(rowFor("live-one")).getByRole("button", { name: "Open on Etsy or Printify" }),
    );
    expect(within(rowFor("live-one")).getByRole("link", { name: /Open on Etsy/ })).toBeVisible();

    fireEvent.mouseDown(document.body);
    expect(
      within(rowFor("live-one")).queryByRole("link", { name: /Open on Etsy/ }),
    ).not.toBeInTheDocument();
  });

  it("offers no open menu on a row with nothing to open", async () => {
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([
      summary({ name: "draft-one", status: "draft" }),
    ]);
    renderPage();
    await findRowLink("draft-one");

    expect(
      within(rowFor("draft-one")).queryByRole("button", { name: "Open on Etsy or Printify" }),
    ).not.toBeInTheDocument();
  });

  it("shows a block-issue badge on a row that has one", async () => {
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([
      summary({ name: "broken-listing", issue_counts: { block: 2, warn: 0 } }),
    ]);
    renderPage();
    await findRowLink("broken-listing");
    expect(within(rowFor("broken-listing")).getByText("2")).toBeInTheDocument();
  });

  it("offers one filter pill per lifecycle state", async () => {
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([
      summary({ name: "draft-one", status: "draft" }),
      summary({ name: "deployed-one", status: "deployed" }),
      summary({ name: "live-one", status: "live" }),
      summary({ name: "dirty-one", status: "dirty" }),
    ]);
    renderPage();
    await findRowLink("draft-one");

    fireEvent.click(screen.getByRole("button", { name: "Live" }));
    expect(queryRowLink("draft-one")).not.toBeInTheDocument();
    expect(queryRowLink("live-one")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Dirty" }));
    expect(queryRowLink("live-one")).not.toBeInTheDocument();
    expect(queryRowLink("dirty-one")).toBeInTheDocument();
  });

  it("filters by the search box", async () => {
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([
      summary({ name: "take-a-hike" }),
      summary({ name: "wildflower-crew" }),
    ]);
    renderPage();
    await findRowLink("take-a-hike");

    fireEvent.change(screen.getByPlaceholderText("Search listings…"), {
      target: { value: "wild" },
    });

    expect(queryRowLink("take-a-hike")).not.toBeInTheDocument();
    expect(queryRowLink("wildflower-crew")).toBeInTheDocument();
  });

  it("navigates to the editor when a listing row is clicked", async () => {
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([summary({ name: "take-a-hike" })]);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "take-a-hike" }));

    await waitFor(() => expect(screen.getByText("editor for take-a-hike")).toBeInTheDocument());
  });

  it("reports a status message when the list fails to load", async () => {
    vi.spyOn(listingsApi, "listListings").mockRejectedValue(new Error("network"));
    renderPage();
    await waitFor(() => expect(screen.getByText("failed to load listings")).toBeInTheDocument());
  });

  it("navigates to the new-listing page when + New listing is clicked", async () => {
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([]);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "+ New listing" }));

    await waitFor(() => expect(screen.getByText("new-listing page")).toBeInTheDocument());
  });
});
