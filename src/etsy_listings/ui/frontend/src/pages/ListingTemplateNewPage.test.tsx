import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import * as templatesApi from "../api/listingTemplates";
import type { ListingTemplateDraft, ListingTemplateSaveResult } from "../types";
import { ListingTemplateNewPage } from "./ListingTemplateNewPage";

function draft(over: Partial<ListingTemplateDraft> = {}): ListingTemplateDraft {
  return {
    name: "",
    modified_at: null,
    garment_profile: "comfort-colors-1717",
    garment: "Comfort Colors 1717",
    colors: ["black", "ivory"],
    prices: { S: "349 NOK", M: "349 NOK" },
    pricing_plan: null,
    pricing_plan_name: null,
    price_overrides: {},
    etsy: {
      description: { text: null, ref: "common-copy/care.md" },
      renewal: null,
      section: "Hiking tees",
      shipping_profile: null,
      variation_images: null,
    },
    media: [{ template: "flat-lay-01", colour: "black" }, "./assets/shots/back.png"],
    issues: [],
    source: { kind: "listing", name: "take-a-hike" },
    assets: [{ ref: "./assets/shots/back.png", source_ref: "./shots/back.png" }],
    resolved_prices: [],
    description_composed: "",
    ...over,
  };
}

function saved(): ListingTemplateSaveResult {
  return { saved: true, issues: [], field_errors: {}, template: null };
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/listing-templates" element={<p>listing templates page</p>} />
        <Route path="/listing-templates/new" element={<ListingTemplateNewPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

async function nameIt(name: string) {
  const field = await screen.findByLabelText("Template name");
  fireEvent.change(field, { target: { value: name } });
  fireEvent.keyDown(field, { key: "Enter" });
}

afterEach(() => vi.restoreAllMocks());

describe("ListingTemplateNewPage", () => {
  it("opens unsaved with the name field focused and empty (UI doc §1)", async () => {
    const get = vi.spyOn(templatesApi, "getListingTemplateDraft").mockResolvedValue(draft());
    renderAt("/listing-templates/new?from_listing=take-a-hike");

    const field = await screen.findByLabelText("Template name");
    expect(field).toHaveValue("");
    expect(field).toHaveFocus();
    expect(field).toHaveAttribute("placeholder", "Name this template…");
    expect(screen.getByText("Not saved — name this template to save it")).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith({ kind: "listing", name: "take-a-hike" });
  });

  it("shows what was kept: garment, colours, pricing, gallery and description source", async () => {
    vi.spyOn(templatesApi, "getListingTemplateDraft").mockResolvedValue(draft());
    const { container } = renderAt("/listing-templates/new?from_listing=take-a-hike");
    await screen.findByLabelText("Template name");

    expect(screen.getByText("Comfort Colors 1717")).toBeInTheDocument();
    expect(screen.getByText("black, ivory")).toBeInTheDocument();
    expect(screen.getByText("Prices set per size: S 349 NOK · M 349 NOK")).toBeInTheDocument();
    expect(screen.getByText("Common copy: common-copy/care.md")).toBeInTheDocument();
    expect(screen.getByText("2 images")).toBeInTheDocument();
    // The copy does not exist until the save, so a local file is drawn from
    // where the listing keeps it.
    const sources = [...container.querySelectorAll(".rtile__face img")].map((img) =>
      img.getAttribute("src"),
    );
    expect(sources).toEqual([
      "/api/templates/flat-lay-01/thumbnail?colour=black",
      "/api/listings/take-a-hike/media-files/shots/back.png/thumbnail",
    ]);
  });

  it("names a pricing plan, and shows inline description text as it will be kept", async () => {
    vi.spyOn(templatesApi, "getListingTemplateDraft").mockResolvedValue(
      draft({
        pricing_plan: "pricing-plans/standard-nok.yaml",
        pricing_plan_name: "standard-nok",
        prices: {},
        etsy: { ...draft().etsy, description: { text: "Garment-dyed cotton.", ref: null } },
      }),
    );
    renderAt("/listing-templates/new?from_listing=take-a-hike");
    await screen.findByLabelText("Template name");

    expect(screen.getByText("Pricing plan: standard-nok")).toBeInTheDocument();
    expect(screen.getByText("Garment-dyed cotton.")).toBeInTheDocument();
  });

  it("has no design, brief, title, tags or lead: those stay with each listing", async () => {
    vi.spyOn(templatesApi, "getListingTemplateDraft").mockResolvedValue(draft());
    renderAt("/listing-templates/new?from_listing=take-a-hike");
    await screen.findByLabelText("Template name");

    for (const label of ["Brief", "Title", "Tags", "Description lead", "Design"]) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });

  it("naming it writes it and lands on the Listing templates page", async () => {
    vi.spyOn(templatesApi, "getListingTemplateDraft").mockResolvedValue(draft());
    const create = vi.spyOn(templatesApi, "createListingTemplate").mockResolvedValue(saved());
    renderAt("/listing-templates/new?from_listing=take-a-hike");

    await nameIt("heavyweight-tee");

    expect(await screen.findByText("listing templates page")).toBeInTheDocument();
    expect(create).toHaveBeenCalledWith("heavyweight-tee", {
      kind: "listing",
      name: "take-a-hike",
    });
  });

  it("refuses a taken name inline and keeps the draft open", async () => {
    vi.spyOn(templatesApi, "getListingTemplateDraft").mockResolvedValue(draft());
    vi.spyOn(templatesApi, "createListingTemplate").mockRejectedValue(
      new templatesApi.ListingTemplateNameRefused("heavyweight-tee", true),
    );
    renderAt("/listing-templates/new?from_listing=take-a-hike");

    await nameIt("heavyweight-tee");

    expect(await screen.findByRole("alert")).toHaveTextContent("that name is already taken");
    expect(screen.getByLabelText("Template name")).toHaveValue("heavyweight-tee");
  });

  it("shows why an incomplete template was not saved", async () => {
    const issue = {
      severity: "block" as const,
      tab: "variants" as const,
      where: "Variants › Colours",
      message: "No colours enabled -- the product would have no variants to sell.",
    };
    vi.spyOn(templatesApi, "getListingTemplateDraft").mockResolvedValue(draft({ issues: [issue] }));
    vi.spyOn(templatesApi, "createListingTemplate").mockResolvedValue({
      saved: false,
      issues: [issue],
      field_errors: {},
      template: null,
    });
    const { container } = renderAt("/listing-templates/new?from_listing=take-a-hike");
    await screen.findByLabelText("Template name");

    const banner = container.querySelector(".issues");
    expect(banner).not.toBeNull();
    expect(
      within(banner as HTMLElement).getByText("1 to fix before this template saves"),
    ).toBeInTheDocument();
    expect(within(banner as HTMLElement).getByText(issue.message)).toBeInTheDocument();

    await nameIt("heavyweight-tee");

    expect(
      await screen.findByText("Not saved — fix the listing it comes from, then name it again"),
    ).toBeInTheDocument();
  });

  it("counts a warning as a warning: it does not stop the save", async () => {
    const warn = {
      severity: "warn" as const,
      tab: "variants" as const,
      where: "Variants › Colours",
      message: "moss not classified light/dark in the garment profile",
    };
    vi.spyOn(templatesApi, "getListingTemplateDraft").mockResolvedValue(draft({ issues: [warn] }));
    renderAt("/listing-templates/new?from_listing=take-a-hike");

    expect(await screen.findByText("1 warning")).toBeInTheDocument();
    expect(screen.queryByText(/to fix before this template saves/)).not.toBeInTheDocument();
  });

  it("clones a listing template, crumb back to the page", async () => {
    const get = vi
      .spyOn(templatesApi, "getListingTemplateDraft")
      .mockResolvedValue(
        draft({ source: { kind: "listing-template", name: "heavyweight-tee" }, assets: [] }),
      );
    renderAt("/listing-templates/new?from_template=heavyweight-tee");
    await screen.findByLabelText("Template name");

    expect(get).toHaveBeenCalledWith({ kind: "listing-template", name: "heavyweight-tee" });
    fireEvent.click(screen.getByText("Listing templates"));
    expect(await screen.findByText("listing templates page")).toBeInTheDocument();
  });

  it("says why a listing cannot become a template", async () => {
    vi.spyOn(templatesApi, "getListingTemplateDraft").mockRejectedValue(
      new templatesApi.ListingTemplatesApiError("./shots/gone.png cannot be copied"),
    );
    renderAt("/listing-templates/new?from_listing=take-a-hike");

    expect(await screen.findByText("./shots/gone.png cannot be copied")).toBeInTheDocument();
  });

  it("needs a source to start from", async () => {
    renderAt("/listing-templates/new");

    expect(
      await screen.findByText(/open a finished listing and choose Save as listing template/),
    ).toBeInTheDocument();
  });
});
