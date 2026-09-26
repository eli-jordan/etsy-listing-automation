import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as listingsApi from "../../api/listings";
import type { ListingDetail } from "../../types";
import { PricingTab } from "./PricingTab";

afterEach(() => {
  vi.restoreAllMocks();
});

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
    pricing_plan_name: "tee-basic",
    resolved_prices: [{ size: "S", amount: "349 NOK" }],
    description_composed: "",
    ...over,
  };
}

describe("PricingTab", () => {
  it("shows the resolved pricing plan and price table", async () => {
    vi.spyOn(listingsApi, "listPricingPlans").mockResolvedValue([
      {
        name: "tee-basic",
        garment_profile: "comfort-colors-1717",
        compatible: true,
        ref: "pricing-plans/tee-basic.yaml",
      },
    ]);
    render(
      <PricingTab
        detail={detail({ pricing_plan: "pricing-plans/tee-basic.yaml" })}
        onUpdate={vi.fn()}
        onFlush={vi.fn()}
      />,
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Plan")).toHaveValue("pricing-plans/tee-basic.yaml"),
    );
    expect(screen.getByText("tee-basic")).toBeInTheDocument();
    expect(screen.getByLabelText("Price for size S")).toHaveValue(349);
    expect(screen.getByText("NOK")).toBeInTheDocument();
  });

  it("selecting a different pricing plan patches pricing_plan with its ref", async () => {
    const onUpdate = vi.fn();
    const onFlush = vi.fn();
    vi.spyOn(listingsApi, "listPricingPlans").mockResolvedValue([
      {
        name: "tee-basic",
        garment_profile: "comfort-colors-1717",
        compatible: true,
        ref: "pricing-plans/tee-basic.yaml",
      },
      {
        name: "tee-premium",
        garment_profile: "comfort-colors-1717",
        compatible: true,
        ref: "pricing-plans/tee-premium.yaml",
      },
    ]);
    render(
      <PricingTab
        detail={detail({ pricing_plan: "pricing-plans/tee-basic.yaml" })}
        onUpdate={onUpdate}
        onFlush={onFlush}
      />,
    );
    await screen.findByText("tee-premium");
    fireEvent.change(screen.getByLabelText("Plan"), {
      target: { value: "pricing-plans/tee-premium.yaml" },
    });
    expect(onUpdate).toHaveBeenCalledWith({ pricing_plan: "pricing-plans/tee-premium.yaml" });
    expect(onFlush).toHaveBeenCalled();
  });

  it("editing a size's price writes a per-size override", async () => {
    const onUpdate = vi.fn();
    render(<PricingTab detail={detail()} onUpdate={onUpdate} onFlush={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Price for size S"), { target: { value: "399" } });
    expect(onUpdate).toHaveBeenCalledWith({ prices: { S: "399 NOK" } });
  });

  it("does not claim every plan is for a different garment when none is chosen", async () => {
    vi.spyOn(listingsApi, "listPricingPlans").mockResolvedValue([
      { name: "tee-basic", garment_profile: "comfort-colors-1717", compatible: false, ref: "r" },
    ]);
    render(
      <PricingTab detail={detail({ garment_profile: "" })} onUpdate={vi.fn()} onFlush={vi.fn()} />,
    );

    const option = await screen.findByRole("option", { name: "tee-basic" });
    expect(option).toBeInTheDocument();
    expect(screen.queryByText(/different garment/)).toBeNull();
  });
});
