import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import * as calibrator from "../api/calibrator";
import * as listingsApi from "../api/listings";
import * as templatesApi from "../api/listingTemplates";
import type { ListingTemplateDetail, ListingTemplateSaveResult } from "../types";
import { ListingTemplateEditorPage } from "./ListingTemplateEditorPage";

/**
 * The listing-template editor (UI doc §3; batch plan PR 6): the listing
 * editor's shell over a listing template, saved only when complete (A36).
 */

function template(over: Partial<ListingTemplateDetail> = {}): ListingTemplateDetail {
  return {
    name: "heavyweight-tee",
    modified_at: "2026-09-27T11:38:00Z",
    garment_profile: "comfort-colors-1717",
    garment: "Comfort Colors 1717",
    colors: ["black", "ivory"],
    prices: { S: "349 NOK" },
    pricing_plan: null,
    pricing_plan_name: null,
    price_overrides: {},
    etsy: {
      description: { text: "Cotton.", ref: null },
      renewal: "auto",
      section: "Hiking tees",
      shipping_profile: null,
      variation_images: null,
    },
    media: [{ template: "flat-lay-01", colour: "black" }],
    issues: [],
    source: null,
    assets: [],
    resolved_prices: [{ size: "S", amount: "349 NOK" }],
    garment_materials: ["cotton"],
    description_composed: "Cotton.",
    ...over,
  };
}

function draft(): ListingTemplateDetail {
  return template({
    name: "",
    modified_at: null,
    source: { kind: "listing", name: "take-a-hike" },
  });
}

function saved(over: Partial<ListingTemplateDetail> = {}): ListingTemplateSaveResult {
  return { saved: true, issues: [], field_errors: {}, template: template(over) };
}

const NO_COLOUR = {
  severity: "block" as const,
  tab: "variants" as const,
  where: "Variants › Colours",
  message: "Turn on at least one colour.",
};

function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      { path: "/listing-templates", element: <p>listing templates page</p> },
      { path: "/listing-templates/new", element: <ListingTemplateEditorPage /> },
      { path: "/listing-templates/:name", element: <ListingTemplateEditorPage /> },
    ],
    { initialEntries: [path] },
  );
  return { router, ...render(<RouterProvider router={router} />) };
}

/** Listing Details' body: the one edit every test can make without a
 * garment profile loaded. */
async function editBody(text: string) {
  fireEvent.click(screen.getByText("Listing Details"));
  const body = await screen.findByLabelText("Description body");
  fireEvent.change(body, { target: { value: text } });
  fireEvent.blur(body);
}

beforeEach(() => {
  vi.spyOn(calibrator, "listTemplates").mockResolvedValue([]);
  vi.spyOn(calibrator, "listDesigns").mockResolvedValue([
    { id: "bundled-grid", label: "Grid / ruler target", source: "bundled" },
  ]);
  vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue([]);
  vi.spyOn(listingsApi, "listListingDesigns").mockResolvedValue([
    { name: "night-hike-club", file: "designs/night-hike-club.png" },
  ]);
  vi.spyOn(listingsApi, "listEtsySections").mockResolvedValue([]);
  vi.spyOn(listingsApi, "listCommonCopy").mockResolvedValue([]);
});

afterEach(() => vi.restoreAllMocks());

// A data router builds a `Request` per navigation with jsdom's
// `AbortSignal`, which Node's own `Request` refuses. The signal is nothing
// these tests look at, so it is dropped rather than the environment changed.
const NodeRequest = globalThis.Request;
beforeAll(() => {
  globalThis.Request = class extends NodeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      const rest = { ...init };
      delete rest.signal;
      super(input, rest);
    }
  } as typeof Request;
});
afterAll(() => {
  globalThis.Request = NodeRequest;
});

describe("ListingTemplateEditorPage, unsaved (UI doc §1)", () => {
  it("opens on the draft with the name field focused and the real tabs", async () => {
    const get = vi.spyOn(templatesApi, "getListingTemplateDraft").mockResolvedValue(draft());
    renderAt("/listing-templates/new?from_listing=take-a-hike");

    const field = await screen.findByLabelText("Template name");
    expect(field).toHaveValue("");
    expect(field).toHaveFocus();
    expect(screen.getByText("Not saved — name this template to save it")).toBeInTheDocument();
    expect(document.querySelector(".tabs")).toHaveTextContent(
      "VariantsPricingListing ImagesListing Details",
    );
    expect(get).toHaveBeenCalledWith({ kind: "listing", name: "take-a-hike" });
  });

  it("naming it writes it with the edits made before, and opens it by name", async () => {
    vi.spyOn(templatesApi, "getListingTemplateDraft").mockResolvedValue(draft());
    const create = vi
      .spyOn(templatesApi, "createListingTemplate")
      .mockResolvedValue(saved({ etsy: { ...template().etsy, description: { text: "Linen." } } }));
    const { router } = renderAt("/listing-templates/new?from_listing=take-a-hike");
    await screen.findByLabelText("Template name");
    await editBody("Linen.");

    const field = screen.getByLabelText("Template name");
    fireEvent.change(field, { target: { value: "heavyweight-tee" } });
    fireEvent.keyDown(field, { key: "Enter" });

    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/listing-templates/heavyweight-tee"),
    );
    const [name, source, document] = create.mock.calls[0] ?? [];
    expect(name).toBe("heavyweight-tee");
    expect(source).toEqual({ kind: "listing", name: "take-a-hike" });
    expect(document).toMatchObject({ etsy: { description: { text: "Linen.", ref: null } } });
    expect(document).not.toHaveProperty("design");
    expect(document).not.toHaveProperty("brief");
  });

  it("offers no Clone or Delete before the template is saved", async () => {
    vi.spyOn(templatesApi, "getListingTemplateDraft").mockResolvedValue(draft());
    renderAt("/listing-templates/new?from_listing=take-a-hike");

    await screen.findByLabelText("Template name");
    expect(screen.queryByRole("button", { name: "Clone" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });

  it("clones from a listing template with the same unsaved state", async () => {
    const get = vi.spyOn(templatesApi, "getListingTemplateDraft").mockResolvedValue({
      ...draft(),
      source: { kind: "listing-template", name: "heavyweight-tee" },
    });
    renderAt("/listing-templates/new?from_template=heavyweight-tee");

    expect(await screen.findByLabelText("Template name")).toHaveValue("");
    expect(get).toHaveBeenCalledWith({ kind: "listing-template", name: "heavyweight-tee" });
  });
});

describe("ListingTemplateEditorPage, saved", () => {
  it("has a head with no status and no Deploy, and the template's file", async () => {
    vi.spyOn(templatesApi, "getListingTemplate").mockResolvedValue(template());
    renderAt("/listing-templates/heavyweight-tee");

    fireEvent.click(await screen.findByRole("button", { name: /^Saved / }));
    expect(screen.getByText("listing-templates/heavyweight-tee/template.yaml")).toBeInTheDocument();
    expect(screen.getByText("Listing templates")).toBeInTheDocument();
    expect(screen.queryByText("Draft")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Deploy/ })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Create listing template" }),
    ).not.toBeInTheDocument();
  });

  it("clones the saved template into the unsaved name-it state (UI doc §3)", async () => {
    vi.spyOn(templatesApi, "getListingTemplate").mockResolvedValue(template());
    const { router } = renderAt("/listing-templates/heavyweight-tee");

    fireEvent.click(await screen.findByRole("button", { name: "Clone" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/listing-templates/new"));
    expect(router.state.location.search).toBe("?from_template=heavyweight-tee");
  });

  it("deletes the saved template after asking, and leaves for the templates page", async () => {
    vi.spyOn(templatesApi, "getListingTemplate").mockResolvedValue(template());
    const del = vi.spyOn(templatesApi, "deleteListingTemplate").mockResolvedValue();
    renderAt("/listing-templates/heavyweight-tee");

    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog", { name: "Delete heavyweight-tee?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));

    expect(await screen.findByText("listing templates page")).toBeInTheDocument();
    expect(del).toHaveBeenCalledWith("heavyweight-tee");
  });

  it("keeps the preview design out of the saved document, and resets it on remount", async () => {
    vi.spyOn(templatesApi, "getListingTemplate").mockResolvedValue(template());
    const put = vi.spyOn(templatesApi, "putListingTemplate").mockResolvedValue(saved());
    const first = renderAt("/listing-templates/heavyweight-tee");

    expect(await screen.findByText("Preview design: Grid / ruler target")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Change preview design" }));
    fireEvent.click(await screen.findByRole("button", { name: /night-hike-club/ }));
    expect(screen.getByText("Preview design: night-hike-club")).toBeInTheDocument();
    await editBody("Linen.");

    await waitFor(() => expect(put).toHaveBeenCalled());
    const document = put.mock.calls[0]?.[1] ?? {};
    expect(JSON.stringify(document)).not.toContain("night-hike-club");
    expect(document).not.toHaveProperty("design");

    first.unmount();
    renderAt("/listing-templates/heavyweight-tee");
    expect(await screen.findByText("Preview design: Grid / ruler target")).toBeInTheDocument();
  });

  it("an incomplete edit is not saved: the head, the banner and the badge say so", async () => {
    vi.spyOn(templatesApi, "getListingTemplate").mockResolvedValue(template());
    vi.spyOn(templatesApi, "putListingTemplate").mockResolvedValue({
      saved: false,
      issues: [NO_COLOUR],
      field_errors: {},
      template: null,
    });
    renderAt("/listing-templates/heavyweight-tee");
    await screen.findByRole("button", { name: /^Saved / });

    await editBody("Linen.");

    expect(
      await screen.findByText("Not saved — fix the highlighted field and it will be written"),
    ).toBeInTheDocument();
    expect(screen.getByText("1 to fix before this template saves")).toBeInTheDocument();
    expect(screen.getByText("Last complete version is kept until then")).toBeInTheDocument();
    expect(screen.queryByText("Prevents deploying")).not.toBeInTheDocument();
    const variants = screen.getByText("Variants");
    expect(within(variants).getByText("1")).toHaveClass("tab-badge");
    // The seller's value is still on screen.
    expect(screen.getByLabelText("Description body")).toHaveValue("Linen.");
  });

  it("warns before navigating away from an unsaved edit", async () => {
    vi.spyOn(templatesApi, "getListingTemplate").mockResolvedValue(template());
    vi.spyOn(templatesApi, "putListingTemplate").mockResolvedValue({
      saved: false,
      issues: [NO_COLOUR],
      field_errors: {},
      template: null,
    });
    const { router } = renderAt("/listing-templates/heavyweight-tee");
    await screen.findByRole("button", { name: /^Saved / });
    await editBody("Linen.");
    await screen.findByText("1 to fix before this template saves");

    fireEvent.click(screen.getByText("Listing templates"));

    const dialog = await screen.findByRole("dialog", {
      name: "Leave without saving this listing template?",
    });
    expect(router.state.location.pathname).toBe("/listing-templates/heavyweight-tee");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(router.state.location.pathname).toBe("/listing-templates/heavyweight-tee");

    fireEvent.click(screen.getByText("Listing templates"));
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Leave" }),
    );
    await waitFor(() => expect(router.state.location.pathname).toBe("/listing-templates"));
  });

  it("renames by the name field, exactly like a listing", async () => {
    vi.spyOn(templatesApi, "getListingTemplate").mockResolvedValue(template());
    const rename = vi
      .spyOn(templatesApi, "renameListingTemplate")
      .mockResolvedValue(template({ name: "everyday-tee" }));
    const { router } = renderAt("/listing-templates/heavyweight-tee");
    await screen.findByRole("button", { name: /^Saved / });

    await act(async () => {
      fireEvent.doubleClick(screen.getByText("heavyweight-tee"));
    });
    const field = screen.getByLabelText("Template name");
    fireEvent.change(field, { target: { value: "everyday-tee" } });
    fireEvent.keyDown(field, { key: "Enter" });

    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/listing-templates/everyday-tee"),
    );
    expect(rename).toHaveBeenCalledWith("heavyweight-tee", "everyday-tee");
  });
});
