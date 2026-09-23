import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import * as calibrator from "../api/calibrator";
import * as listingsApi from "../api/listings";
import type { ListingDetail } from "../types";
import { ListingEditorPage } from "./ListingEditorPage";

function detail(over: Partial<ListingDetail> = {}): ListingDetail {
  return {
    garment_profile: "comfort-colors-1717",
    design: { default: "../../designs/take-a-hike.png" },
    colors: ["black"],
    brief: "",
    prices: {},
    price_overrides: {},
    artwork: {},
    pricing_plan: null,
    etsy: {
      title: "",
      description: { lead: "", text: null, ref: null },
      tags: [],
      variation_images: null,
      renewal: null,
      section: null,
      shipping_profile: null,
    },
    media: [],
    name: "take-a-hike",
    modified_at: "2026-09-17T10:00:00Z",
    status: "draft",
    issues: [],
    field_errors: {},
    etsy_listing_id: null,
    printify_product_id: null,
    pricing_plan_name: null,
    resolved_prices: [],
    description_composed: "",
    ...over,
  };
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/listings" element={<p>listings page</p>} />
        <Route path="/listings/new" element={<ListingEditorPage />} />
        <Route path="/listings/:name" element={<ListingEditorPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.spyOn(calibrator, "listTemplates").mockResolvedValue([]);
  vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue([]);
  vi.spyOn(listingsApi, "listListingDesigns").mockResolvedValue([]);
});

afterEach(() => vi.restoreAllMocks());

describe("ListingEditorPage", () => {
  it("loads the listing and shows its name, defaulting to the Variants tab", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(detail());
    renderAt("/listings/take-a-hike");

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "take-a-hike" })).toBeInTheDocument(),
    );
    expect(screen.getByLabelText("Garment profile")).toBeInTheDocument();
  });

  it("switches tabs", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(detail());
    renderAt("/listings/take-a-hike");
    await screen.findByRole("heading", { name: "take-a-hike" });

    fireEvent.click(screen.getByText("Listing Details"));
    expect(screen.getByLabelText("Title")).toBeInTheDocument();
  });

  it("flushes a pending edit when switching tabs", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(detail());
    const patchSpy = vi.spyOn(listingsApi, "patchListing").mockResolvedValue(detail());
    renderAt("/listings/take-a-hike");
    await screen.findByRole("heading", { name: "take-a-hike" });

    fireEvent.click(screen.getByText("Listing Details"));
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Take A Hike Tee" } });

    fireEvent.click(screen.getByText("Variants"));
    await waitFor(() =>
      expect(patchSpy).toHaveBeenCalledWith("take-a-hike", { etsy: { title: "Take A Hike Tee" } }),
    );
  });

  it("shows the issues banner with a block/warn count", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(
      detail({
        issues: [
          { severity: "block", tab: "details", where: "Title", message: "still <generate>" },
          { severity: "warn", tab: "details", where: "Tags", message: "no tags" },
        ],
      }),
    );
    renderAt("/listings/take-a-hike");
    await screen.findByText(/1 problem blocks this listing/);
    expect(screen.getByText("still <generate>")).toBeInTheDocument();
  });

  it("counts warnings in the summary alongside the blocks", async () => {
    /* Reporting only the blocks left "1 problem blocks this listing" sitting
       above three issues, two of which the summary never mentioned. */
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(
      detail({
        issues: [
          { severity: "block", tab: "details", where: "Title", message: "still <generate>" },
          { severity: "warn", tab: "details", where: "Tags", message: "no tags" },
          { severity: "warn", tab: "images", where: "Swatches", message: "ivory uncovered" },
        ],
      }),
    );
    renderAt("/listings/take-a-hike");

    await screen.findByText("1 problem blocks this listing · 2 warnings");
  });

  it("summarises warnings alone when nothing blocks", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(
      detail({
        issues: [{ severity: "warn", tab: "details", where: "Tags", message: "no tags" }],
      }),
    );
    renderAt("/listings/take-a-hike");

    await screen.findByText("1 warning");
  });

  it("pluralises blocking problems", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(
      detail({
        issues: [
          { severity: "block", tab: "details", where: "Title", message: "a" },
          { severity: "block", tab: "images", where: "Media", message: "b" },
        ],
      }),
    );
    renderAt("/listings/take-a-hike");

    await screen.findByText("2 problems block this listing");
  });

  it("jumps to the tab that owns an issue when Fix is clicked", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(
      detail({
        issues: [
          { severity: "block", tab: "details", where: "Title", message: "still <generate>" },
        ],
      }),
    );
    renderAt("/listings/take-a-hike");
    await screen.findByText("still <generate>");
    expect(screen.queryByLabelText("Title")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Fix: still <generate>" }));

    expect(screen.getByLabelText("Title")).toBeInTheDocument();
  });

  it("says «Below» rather than «Fix» for an issue on the tab already open", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(
      detail({
        issues: [{ severity: "block", tab: "variants", where: "Colours", message: "no colours" }],
      }),
    );
    renderAt("/listings/take-a-hike");

    await screen.findByText("Below");
  });

  it("carries the design strip above the tabs, where both tabs can see it", async () => {
    vi.spyOn(listingsApi, "listListingDesigns").mockResolvedValue([
      { name: "take-a-hike", file: "designs/take-a-hike.png" },
    ]);
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(detail());
    renderAt("/listings/take-a-hike");

    expect(await screen.findByText("designs/take-a-hike.png")).toBeInTheDocument();
  });

  it("saves a newly picked design", async () => {
    vi.spyOn(listingsApi, "listListingDesigns").mockResolvedValue([
      { name: "take-a-hike", file: "designs/take-a-hike.png" },
      { name: "cosmic-cat", file: "designs/cosmic-cat.png" },
    ]);
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(detail());
    const patchSpy = vi.spyOn(listingsApi, "patchListing").mockResolvedValue(detail());
    renderAt("/listings/take-a-hike");
    await screen.findByText("designs/take-a-hike.png");

    fireEvent.click(screen.getByRole("button", { name: /Change design/ }));
    fireEvent.click(screen.getByRole("button", { name: /cosmic-cat/ }));

    await waitFor(() =>
      expect(patchSpy).toHaveBeenCalledWith("take-a-hike", {
        design: "../../designs/cosmic-cat.png",
      }),
    );
  });

  it("shows the listing's path on disk in the page head", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(detail());
    renderAt("/listings/take-a-hike");

    await screen.findByText("listings/take-a-hike/listing.yaml");
  });

  it("shows a badge on the tab that owns an issue", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(
      detail({
        issues: [
          { severity: "block", tab: "images", where: "Listing Images", message: "no media" },
        ],
      }),
    );
    const { container } = renderAt("/listings/take-a-hike");
    await screen.findByRole("heading", { name: "take-a-hike" });
    const imagesTabButton = Array.from(container.querySelectorAll(".seg-opt")).find((el) =>
      el.textContent?.startsWith("Listing Images"),
    ) as HTMLElement;
    expect(imagesTabButton.querySelector(".tab-badge--block")).toHaveTextContent("1");
  });

  it("shows Draft for an unpublished listing and no open-elsewhere menu", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(detail({ status: "draft" }));
    renderAt("/listings/take-a-hike");
    await screen.findByText("Draft");
    expect(screen.queryByTitle("Open on Etsy or Printify")).not.toBeInTheDocument();
  });

  it("links a live listing at its own Etsy listing editor", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(
      detail({ status: "live", etsy_listing_id: 4572960161 }),
    );
    renderAt("/listings/take-a-hike");
    await screen.findByText("Live");

    fireEvent.click(screen.getByTitle("Open on Etsy or Printify"));
    const link = screen.getByRole("link", { name: /Open on Etsy/ });
    expect(link).toHaveAttribute(
      "href",
      "https://www.etsy.com/your/shops/me/listing-editor/edit/4572960161",
    );
  });

  it("links a listing with only a Printify product at that product", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(
      detail({ status: "deployed", printify_product_id: "6aa332559f8d2ff30103b4c9" }),
    );
    renderAt("/listings/take-a-hike");
    await screen.findByText("Deployed");

    fireEvent.click(screen.getByTitle("Open on Etsy or Printify"));
    expect(screen.getByRole("link", { name: /Open on Printify/ })).toHaveAttribute(
      "href",
      "https://printify.com/app/product-details/6aa332559f8d2ff30103b4c9",
    );
    expect(screen.queryByRole("link", { name: /Open on Etsy/ })).not.toBeInTheDocument();
  });

  it("goes back to the listings page when the breadcrumb is clicked", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(detail());
    renderAt("/listings/take-a-hike");
    await screen.findByRole("heading", { name: "take-a-hike" });

    fireEvent.click(screen.getByText("Listings"));
    await waitFor(() => expect(screen.getByText("listings page")).toBeInTheDocument());
  });

  it("reports a load failure", async () => {
    vi.spyOn(listingsApi, "getListing").mockRejectedValue(new Error("404"));
    renderAt("/listings/does-not-exist");
    await waitFor(() =>
      expect(screen.getByText("failed to load listing does-not-exist")).toBeInTheDocument(),
    );
  });
});

describe("ListingEditorPage at /listings/new", () => {
  const draft = () =>
    detail({ name: "", garment_profile: "", design: {}, colors: [], prices: {}, media: [] });

  it("opens the editor itself, on a draft, with the name waiting to be typed", async () => {
    vi.spyOn(listingsApi, "getListingDraft").mockResolvedValue(draft());
    renderAt("/listings/new");

    await waitFor(() => expect(screen.getByLabelText("Listing name")).toBeInTheDocument());
    // The same editor, not a second form: the tabs are right there.
    expect(screen.getByLabelText("Garment profile")).toBeInTheDocument();
  });

  it("says what is standing between the draft and a file on disk", async () => {
    vi.spyOn(listingsApi, "getListingDraft").mockResolvedValue(draft());
    renderAt("/listings/new");

    await waitFor(() =>
      expect(screen.getByText(/double-click the name above/i)).toBeInTheDocument(),
    );
  });

  it("naming it creates it and replaces the route with the real editor", async () => {
    vi.spyOn(listingsApi, "getListingDraft").mockResolvedValue(draft());
    const create = vi
      .spyOn(listingsApi, "createListing")
      .mockResolvedValue(detail({ name: "my-shirt" }));
    const get = vi.spyOn(listingsApi, "getListing").mockResolvedValue(detail({ name: "my-shirt" }));
    renderAt("/listings/new");

    const input = await screen.findByLabelText("Listing name");
    fireEvent.change(input, { target: { value: "my-shirt" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "my-shirt" })).toBeInTheDocument(),
    );
    expect(create).toHaveBeenCalledTimes(1);
    // The listing rode along in the navigation: the new route mounts a fresh
    // editor, and making it re-fetch would open a window for a GET to answer
    // with a document older than the create that just landed.
    expect(get).not.toHaveBeenCalled();
  });

  it("explains a draft that cannot be started at all", async () => {
    vi.spyOn(listingsApi, "getListingDraft").mockRejectedValue(new Error("nope"));
    renderAt("/listings/new");

    await waitFor(() =>
      expect(screen.getByText("could not start a new listing")).toBeInTheDocument(),
    );
  });
});

describe("ListingEditorPage renaming", () => {
  it("double-clicking the title renames the listing and follows it to the new URL", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(detail());
    const rename = vi
      .spyOn(listingsApi, "renameListing")
      .mockResolvedValue(detail({ name: "hike-away" }));
    renderAt("/listings/take-a-hike");

    fireEvent.doubleClick(await screen.findByRole("heading", { name: "take-a-hike" }));
    const input = screen.getByLabelText("Listing name");
    fireEvent.change(input, { target: { value: "hike-away" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "hike-away" })).toBeInTheDocument(),
    );
    expect(rename).toHaveBeenCalledWith("take-a-hike", "hike-away");
  });

  it("a refused rename says so and leaves the listing where it was", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(detail());
    vi.spyOn(listingsApi, "renameListing").mockRejectedValue(
      new listingsApi.ListingsApiError("409"),
    );
    renderAt("/listings/take-a-hike");

    fireEvent.doubleClick(await screen.findByRole("heading", { name: "take-a-hike" }));
    const input = screen.getByLabelText("Listing name");
    fireEvent.change(input, { target: { value: "taken" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(screen.getByText(/already a listing called/i)).toBeInTheDocument());
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("has no delete or retire buttons — those live on the listings table", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(detail());
    renderAt("/listings/take-a-hike");
    await screen.findByRole("heading", { name: "take-a-hike" });

    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retire" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Un-retire" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Renew" })).not.toBeInTheDocument();
  });
});
