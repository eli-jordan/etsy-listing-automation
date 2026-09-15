import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as listingsApi from "../../api/listings";
import type { ListingDetail } from "../../types";
import { VariantsTab } from "./VariantsTab";

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

afterEach(() => vi.restoreAllMocks());

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
