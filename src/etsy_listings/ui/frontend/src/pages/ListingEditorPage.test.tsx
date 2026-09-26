import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import * as calibrator from "../api/calibrator";
import * as listingsApi from "../api/listings";
import * as seoApi from "../api/seo";
import { briefEvent, type FakeAiRuns, fakeAiRuns, stepEvent } from "../test/aiRuns";
import type { ListingDetail } from "../types";
import { ListingEditorPage } from "./ListingEditorPage";

function detail(over: Partial<ListingDetail> = {}): ListingDetail {
  return {
    garment_profile: "comfort-colors-1717",
    design: { default: "designs/take-a-hike.png" },
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

let runs: FakeAiRuns;

beforeEach(() => {
  runs = fakeAiRuns();
  vi.spyOn(calibrator, "listTemplates").mockResolvedValue([]);
  vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue([]);
  vi.spyOn(listingsApi, "listListingDesigns").mockResolvedValue([]);
  // The editor asks these as soon as a saved listing has a design, brief or
  // not. A fixture that never opens Listing Details still mounts the hook.
  vi.spyOn(listingsApi, "getWorkspace").mockResolvedValue({
    shop_name: "Pine & Thread",
    storage_id: "workspace-1",
  });
  vi.spyOn(seoApi, "getSeoReadiness").mockResolvedValue({ ready: false });
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
    expect(screen.queryByLabelText("Plan")).not.toBeInTheDocument();
  });

  it("shows pricing on its own tab, immediately after Variants", async () => {
    vi.spyOn(listingsApi, "listPricingPlans").mockResolvedValue([]);
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(
      detail({ resolved_prices: [{ size: "S", amount: "349 NOK" }] }),
    );
    const { container } = renderAt("/listings/take-a-hike");
    await screen.findByRole("heading", { name: "take-a-hike" });

    const labels = [...container.querySelectorAll(".tabs .seg-opt")].map((el) =>
      el.textContent?.replace(/\d+/g, "").trim(),
    );
    expect(labels).toEqual(["Variants", "Pricing", "Listing Images", "Listing Details"]);

    fireEvent.click(screen.getByText("Pricing"));
    expect(screen.getByLabelText("Plan")).toBeInTheDocument();
    expect(screen.getByLabelText("Price for size S")).toBeInTheDocument();
    expect(screen.queryByLabelText("Title")).not.toBeInTheDocument();
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
    await screen.findByText(/1 to fix before deploying/);
    expect(screen.getByText("still <generate>")).toBeInTheDocument();
  });

  it("presents deploy blockers as warnings, marked in words (PRD 70)", async () => {
    /* None of these stops the save -- naming the listing wrote it -- so an
       error's red circle told a seller their work was refused. A blocker
       wears the warning icon like everything else, and says what it stops
       on its own row, so the difference from plain advice is not colour. */
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(
      detail({
        issues: [
          { severity: "block", tab: "details", where: "Title", message: "no title" },
          { severity: "warn", tab: "details", where: "Tags", message: "no tags" },
        ],
      }),
    );
    const { container } = renderAt("/listings/take-a-hike");
    await screen.findByText("no title");

    expect(container.querySelector(".issue--block")).toBeNull();
    expect(container.querySelectorAll(".issue--warn")).toHaveLength(2);
    expect(screen.getAllByText("Prevents deploying")).toHaveLength(1);
  });

  it("counts warnings in the summary alongside the blocks", async () => {
    /* Reporting only the blocks left a one-item summary sitting above three
       issues, two of which it never mentioned. */
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

    await screen.findByText("1 to fix before deploying · 2 other warnings");
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

  it("shows an info note quietly: no warning icon, and never counted as a warning", async () => {
    /* PRD 72: Etsy strips a video's sound. Worth saying, nothing to fix. */
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(
      detail({
        issues: [
          { severity: "warn", tab: "details", where: "Tags", message: "no tags" },
          { severity: "info", tab: "images", where: "Clip", message: "sound is stripped" },
        ],
      }),
    );
    const { container } = renderAt("/listings/take-a-hike");

    await screen.findByText("1 warning · 1 note");
    const note = screen.getByText("sound is stripped").closest(".issue");
    expect(note).toHaveClass("issue--info");
    expect(note?.querySelector(".issue__icon svg")).toBeNull();
    expect(container.querySelectorAll(".issue--warn")).toHaveLength(1);
  });

  it("summarises a note alone as a note, not a warning", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(
      detail({
        issues: [{ severity: "info", tab: "images", where: "Clip", message: "sound is stripped" }],
      }),
    );
    renderAt("/listings/take-a-hike");

    await screen.findByText("1 note");
  });

  it("pluralises notes", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(
      detail({
        issues: [
          { severity: "info", tab: "images", where: "A", message: "a is silent" },
          { severity: "info", tab: "images", where: "B", message: "b is silent" },
        ],
      }),
    );
    renderAt("/listings/take-a-hike");

    await screen.findByText("2 notes");
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

    await screen.findByText("2 to fix before deploying");
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
    fireEvent.click(await screen.findByRole("button", { name: /cosmic-cat/ }));

    await waitFor(() =>
      expect(patchSpy).toHaveBeenCalledWith("take-a-hike", {
        design: "designs/cosmic-cat.png",
      }),
    );
  });

  it("runs the AI chain once the picked design is saved, and fills in the brief it drafts", async () => {
    /* PRD 68: a pick on a listing whose brief is empty arms the chain; the
       save that follows fires it. The server writes the drafted brief, so
       the field fills in without another save. */
    vi.spyOn(listingsApi, "listListingDesigns").mockResolvedValue([
      { name: "take-a-hike", file: "designs/take-a-hike.png" },
      { name: "cosmic-cat", file: "designs/cosmic-cat.png" },
    ]);
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(detail());
    const patchSpy = vi
      .spyOn(listingsApi, "patchListing")
      .mockResolvedValue(detail({ design: { default: "designs/cosmic-cat.png" } }));
    renderAt("/listings/take-a-hike");
    await screen.findByText("designs/take-a-hike.png");

    fireEvent.click(screen.getByRole("button", { name: /Change design/ }));
    fireEvent.click(await screen.findByRole("button", { name: /cosmic-cat/ }));

    await waitFor(() =>
      expect(runs.start).toHaveBeenCalledWith("take-a-hike", { draftBrief: true }),
    );
    await waitFor(() => expect(runs.streams).toHaveLength(1));
    runs.emit(stepEvent("brief", "active", "Reading cosmic-cat.png"));
    expect(screen.getByText("Drafting brief…")).toBeInTheDocument();
    // Still on Variants: the details tab is unmounted, and the notice has to
    // be up anyway, at the moment the run starts. It is portaled to the
    // document, so leaving Variants does not take it with the tab.
    const notice = "AI Mode is writing a title, tags and a description from this design.";
    expect(screen.queryByLabelText("Brief")).not.toBeInTheDocument();
    const toast = screen.getByText(notice).closest(".ai-auto-toast");
    expect(toast?.parentElement).toBe(document.body);
    expect(document.querySelector(".editor .ai-auto-toast")).toBeNull();

    vi.spyOn(listingsApi, "listPricingPlans").mockResolvedValue([]);
    vi.spyOn(listingsApi, "listCommonMedia").mockResolvedValue([]);
    for (const tab of ["Pricing", "Listing Images", "Listing Details"]) {
      fireEvent.click(screen.getByText(tab));
      expect(screen.getByText(notice)).toBeInTheDocument();
      expect(screen.getByText(notice).closest(".details-tab")).toBeNull();
    }

    fireEvent.click(screen.getByText("Listing Details"));
    runs.emit(briefEvent("A cat in a spacesuit."), stepEvent("brief", "done"));

    expect(screen.getByLabelText("Brief")).toHaveValue("A cat in a spacesuit.");
    expect(patchSpy).toHaveBeenCalledTimes(1);
  });

  it("does not rename a listing that already has a name when its design changes", async () => {
    /* A listing called something is called that on purpose. Only a draft
       with no name at all takes one from its artwork. */
    vi.spyOn(listingsApi, "listListingDesigns").mockResolvedValue([
      { name: "take-a-hike", file: "designs/take-a-hike.png" },
      { name: "cosmic-cat", file: "designs/cosmic-cat.png" },
    ]);
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(detail());
    vi.spyOn(listingsApi, "patchListing").mockResolvedValue(detail());
    const rename = vi.spyOn(listingsApi, "renameListing");
    renderAt("/listings/take-a-hike");
    await screen.findByText("designs/take-a-hike.png");

    fireEvent.click(screen.getByRole("button", { name: /Change design/ }));
    fireEvent.click(await screen.findByRole("button", { name: /cosmic-cat/ }));

    await waitFor(() => expect(listingsApi.patchListing).toHaveBeenCalled());
    expect(rename).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "take-a-hike" })).toBeInTheDocument();
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
    // A warning-coloured count: the tab only says there is something to look
    // at, and none of it stops the save.
    expect(imagesTabButton.querySelector(".tab-badge--warn")).toHaveTextContent("1");
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

  it("takes its name from the design's filename when it has none", async () => {
    /* The ordinary create flow becomes "pick a design": that is what names
       the draft, and naming is what writes the file. */
    vi.spyOn(listingsApi, "getListingDraft").mockResolvedValue(draft());
    vi.spyOn(listingsApi, "listListingDesigns").mockResolvedValue([
      { name: "cosmic-cat", file: "designs/cosmic-cat.png" },
    ]);
    const create = vi
      .spyOn(listingsApi, "createListing")
      .mockResolvedValue(detail({ name: "cosmic-cat" }));
    renderAt("/listings/new");
    await screen.findByLabelText("Listing name");

    fireEvent.click(screen.getByRole("button", { name: /Change design/ }));
    fireEvent.click(await screen.findByRole("button", { name: /cosmic-cat/ }));

    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create.mock.calls[0]?.[0].name).toBe("cosmic-cat");
    // The design it was named after is in the document that created it, not
    // in a follow-up patch: `useAutosave` merges what is pending into the
    // create candidate.
    expect(create.mock.calls[0]?.[0].document).toMatchObject({
      design: "designs/cosmic-cat.png",
    });
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "cosmic-cat" })).toBeInTheDocument(),
    );
  });

  it("shows the picked name even while the listing still cannot be written", async () => {
    /* A create is refused until the document validates -- no price source,
       usually. Without this the seller picks a design, watches the name field
       stay empty, picks a pricing plan, and finds the listing suddenly called
       something nobody typed. */
    vi.spyOn(listingsApi, "getListingDraft").mockResolvedValue(draft());
    vi.spyOn(listingsApi, "listListingDesigns").mockResolvedValue([
      { name: "cosmic-cat", file: "designs/cosmic-cat.png" },
    ]);
    // What the server answers for a document it will not write: the empty
    // draft back, with the reasons.
    vi.spyOn(listingsApi, "createListing").mockResolvedValue(
      detail({ name: "", field_errors: { pricing_plan: "no price source" } }),
    );
    renderAt("/listings/new");
    await screen.findByLabelText("Listing name");

    fireEvent.click(screen.getByRole("button", { name: /Change design/ }));
    fireEvent.click(await screen.findByRole("button", { name: /cosmic-cat/ }));

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "cosmic-cat" })).toBeInTheDocument(),
    );
  });

  it("leaves a name the seller is part-way through typing alone", async () => {
    /* An uncommitted name is not the listing's name -- `detail.name` is still
       empty -- so the pick has to be told about the field's own text or it
       would overwrite what they were in the middle of writing. */
    vi.spyOn(listingsApi, "getListingDraft").mockResolvedValue(draft());
    vi.spyOn(listingsApi, "listListingDesigns").mockResolvedValue([
      { name: "cosmic-cat", file: "designs/cosmic-cat.png" },
    ]);
    const create = vi.spyOn(listingsApi, "createListing");
    const describe = vi
      .spyOn(listingsApi, "describeListingDraft")
      .mockResolvedValue({ ...draft(), design: { default: "designs/cosmic-cat.png" } });
    renderAt("/listings/new");

    const input = await screen.findByLabelText("Listing name");
    fireEvent.change(input, { target: { value: "my-shi" } });

    fireEvent.click(screen.getByRole("button", { name: /Change design/ }));
    fireEvent.click(await screen.findByRole("button", { name: /cosmic-cat/ }));

    await waitFor(() => expect(describe).toHaveBeenCalled());
    expect(create).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Listing name")).toHaveValue("my-shi");

    // Unmount here rather than in the shared cleanup: this is the one test
    // that ends with an edit still pending on an *unnamed* draft, so
    // `useAutosave`'s flush-on-unmount describes it -- and the shared
    // `afterEach` has already restored the mock by the time that runs.
    cleanup();
  });

  it("keeps a name the seller already typed, even if the design is picked after", async () => {
    vi.spyOn(listingsApi, "getListingDraft").mockResolvedValue(draft());
    vi.spyOn(listingsApi, "listListingDesigns").mockResolvedValue([
      { name: "cosmic-cat", file: "designs/cosmic-cat.png" },
    ]);
    const create = vi
      .spyOn(listingsApi, "createListing")
      .mockResolvedValue(detail({ name: "my-shirt" }));
    vi.spyOn(listingsApi, "patchListing").mockResolvedValue(detail({ name: "my-shirt" }));
    renderAt("/listings/new");

    const input = await screen.findByLabelText("Listing name");
    fireEvent.change(input, { target: { value: "my-shirt" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "my-shirt" })).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: /Change design/ }));
    fireEvent.click(await screen.findByRole("button", { name: /cosmic-cat/ }));

    await waitFor(() => expect(listingsApi.patchListing).toHaveBeenCalled());
    expect(create).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("heading", { name: "my-shirt" })).toBeInTheDocument();
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
