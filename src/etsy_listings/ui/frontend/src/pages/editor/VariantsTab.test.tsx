import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as calibrator from "../../api/calibrator";
import * as listingsApi from "../../api/listings";
import type { GarmentProfileSummary, ListingDetail, TemplateSummary } from "../../types";
import { VariantsTab } from "./VariantsTab";

function template(over: Partial<TemplateSummary> & { name: string }): TemplateSummary {
  return {
    kind: "colour-matrix",
    colours: ["black", "ivory"],
    has_config: true,
    status: "calibrated",
    status_reason: null,
    width: 480,
    height: 576,
    ...over,
  };
}

function detail(over: Partial<ListingDetail> = {}): ListingDetail {
  return {
    garment_profile: "comfort-colors-1717",
    design: {},
    colors: ["black"],
    brief: "",
    prices: {},
    price_overrides: {},
    artwork: {},
    pricing_plan: null,
    etsy: {
      title: "<generate>",
      description: "<generate>",
      tags: "<generate>",
      materials: [],
      variation_images: null,
      renewal: null,
      section: null,
      shipping_profile: null,
    },
    media: [],
    name: "take-a-hike",
    status: "draft",
    issues: [],
    field_errors: {},
    etsy_listing_id: null,
    printify_product_id: null,
    pricing_plan_name: null,
    resolved_prices: [],
    ...over,
  };
}

beforeEach(() => {
  vi.spyOn(calibrator, "listTemplates").mockResolvedValue([]);
});

afterEach(() => vi.restoreAllMocks());

describe("VariantsTab's preview", () => {
  const profiles: GarmentProfileSummary[] = [
    { name: "comfort-colors-1717", sizes: ["S"], colors: { black: "dark", ivory: "light" } },
  ];

  function renderWithFlatLay(over: Partial<ListingDetail> = {}) {
    vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue(profiles);
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([template({ name: "flat-lay-01" })]);
    return render(
      <VariantsTab
        detail={detail({
          colors: ["black", "ivory"],
          media: [{ template: "flat-lay-01", colour: "black" }],
          ...over,
        })}
        onUpdate={vi.fn()}
      />,
    );
  }

  it("previews the first enabled colour's real photo", async () => {
    renderWithFlatLay();
    const preview = await screen.findByAltText("black on flat-lay-01");
    expect(preview).toHaveAttribute("src", "/api/templates/flat-lay-01/thumbnail?colour=black");
  });

  it("previews whichever colour was clicked", async () => {
    renderWithFlatLay();
    await screen.findByAltText("black on flat-lay-01");

    fireEvent.click(screen.getByRole("button", { name: "Preview ivory" }));

    expect(await screen.findByAltText("ivory on flat-lay-01")).toHaveAttribute(
      "src",
      "/api/templates/flat-lay-01/thumbnail?colour=ivory",
    );
  });

  it("marks exactly one colour row as the previewed one", async () => {
    const { container } = renderWithFlatLay();
    await screen.findByAltText("black on flat-lay-01");
    expect(container.querySelectorAll(".color-row--selected")).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Preview ivory" }));
    expect(container.querySelectorAll(".color-row--selected")).toHaveLength(1);
  });

  it("dims a colour the listing has switched off rather than hiding it", async () => {
    const { container } = renderWithFlatLay({ colors: ["black"] });
    await screen.findByText("ivory");

    const ivoryRow = screen.getByText("ivory").closest(".color-row");
    expect(ivoryRow).toHaveClass("color-row--off");
    expect(container.querySelector(".color-row--selected")).not.toHaveClass("color-row--off");
  });

  it("explains itself when the listing uses no colour-matrix template", async () => {
    vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue(profiles);
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([
      template({ name: "sizing-chart", kind: "single", colours: [] }),
    ]);
    render(
      <VariantsTab
        detail={detail({ colors: ["black"], media: [{ template: "sizing-chart", colour: null }] })}
        onUpdate={vi.fn()}
      />,
    );

    expect(
      await screen.findByText(/Add a colour-matrix mockup on Listing Images/),
    ).toBeInTheDocument();
  });
});

describe("VariantsTab", () => {
  it("shows the garment profile's sizes once profiles load", async () => {
    vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue([
      { name: "comfort-colors-1717", sizes: ["S", "M", "L"], colors: { black: "dark" } },
    ]);
    render(<VariantsTab detail={detail()} onUpdate={vi.fn()} />);
    await screen.findByText("S");
    expect(screen.getByText("M")).toBeInTheDocument();
    expect(screen.getByText("L")).toBeInTheDocument();
  });

  it("lists every colour the profile classifies, with its light/dark badge", async () => {
    vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue([
      { name: "comfort-colors-1717", sizes: ["S"], colors: { black: "dark", white: "light" } },
    ]);
    render(<VariantsTab detail={detail({ colors: ["black"] })} onUpdate={vi.fn()} />);

    await screen.findByText("black");
    expect(screen.getByText("white")).toBeInTheDocument();
    expect(screen.getByText("dark")).toBeInTheDocument();
    expect(screen.getByText("light")).toBeInTheDocument();
  });

  it("keeps a colour the listing enables even if the profile doesn't classify it", async () => {
    vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue([
      { name: "comfort-colors-1717", sizes: ["S"], colors: {} },
    ]);
    render(<VariantsTab detail={detail({ colors: ["forest"] })} onUpdate={vi.fn()} />);
    await screen.findByText("forest");
  });

  it("toggling a colour off removes it from colors", async () => {
    vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue([
      { name: "comfort-colors-1717", sizes: ["S"], colors: { black: "dark" } },
    ]);
    const onUpdate = vi.fn();
    render(<VariantsTab detail={detail({ colors: ["black"] })} onUpdate={onUpdate} />);

    fireEvent.click(await screen.findByRole("switch", { name: "black" }));
    expect(onUpdate).toHaveBeenCalledWith({ colors: [] });
  });

  it("toggling a colour on adds it to colors", async () => {
    vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue([
      { name: "comfort-colors-1717", sizes: ["S"], colors: { black: "dark", white: "light" } },
    ]);
    const onUpdate = vi.fn();
    render(<VariantsTab detail={detail({ colors: ["black"] })} onUpdate={onUpdate} />);

    fireEvent.click(await screen.findByRole("switch", { name: "white" }));
    expect(onUpdate).toHaveBeenCalledWith({ colors: ["black", "white"] });
  });

  it("changing the garment profile dropdown updates garment_profile", async () => {
    vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue([
      { name: "comfort-colors-1717", sizes: ["S"], colors: {} },
      { name: "gildan-5000", sizes: ["S"], colors: {} },
    ]);
    const onUpdate = vi.fn();
    render(<VariantsTab detail={detail()} onUpdate={onUpdate} />);

    await waitFor(() =>
      expect(screen.getByRole("option", { name: "gildan-5000" })).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText("Garment profile"), {
      target: { value: "gildan-5000" },
    });
    expect(onUpdate).toHaveBeenCalledWith({ garment_profile: "gildan-5000" });
  });
});
