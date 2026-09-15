import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ListingDetail } from "../../types";
import { DetailsTab } from "./DetailsTab";

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
      tags: ["Botanical", "Gift"],
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
    pricing_plan_name: "tee-basic",
    resolved_prices: [{ size: "S", amount: "349 NOK" }],
    ...over,
  };
}

describe("DetailsTab", () => {
  it("renders the current title, description and tags", () => {
    render(<DetailsTab detail={detail()} onUpdate={vi.fn()} onFlush={vi.fn()} />);
    expect(screen.getByLabelText("Title")).toHaveValue("<generate>");
    expect(screen.getByLabelText("Description")).toHaveValue("<generate>");
    expect(screen.getByText("Botanical")).toBeInTheDocument();
    expect(screen.getByText("Gift")).toBeInTheDocument();
  });

  it("typing in the title updates etsy.title", () => {
    const onUpdate = vi.fn();
    render(<DetailsTab detail={detail()} onUpdate={onUpdate} onFlush={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Take A Hike Tee" } });
    expect(onUpdate).toHaveBeenCalledWith({ etsy: { title: "Take A Hike Tee" } });
  });

  it("flushes on blur so a tab switch never loses the last keystroke", () => {
    const onFlush = vi.fn();
    render(<DetailsTab detail={detail()} onUpdate={vi.fn()} onFlush={onFlush} />);
    fireEvent.blur(screen.getByLabelText("Title"));
    expect(onFlush).toHaveBeenCalled();
  });

  it("shows a field error inline under the title", () => {
    render(
      <DetailsTab
        detail={detail({ field_errors: { "etsy.title": "title is too long" } })}
        onUpdate={vi.fn()}
        onFlush={vi.fn()}
      />,
    );
    expect(screen.getByText("title is too long")).toBeInTheDocument();
  });

  it("removes a tag when its × is clicked", () => {
    const onUpdate = vi.fn();
    render(<DetailsTab detail={detail()} onUpdate={onUpdate} onFlush={vi.fn()} />);
    fireEvent.click(screen.getByText("Botanical").querySelector(".chip__x") as Element);
    expect(onUpdate).toHaveBeenCalledWith({ etsy: { tags: ["Gift"] } });
  });

  it("adds tags typed comma-separated on Enter", () => {
    const onUpdate = vi.fn();
    render(<DetailsTab detail={detail()} onUpdate={onUpdate} onFlush={vi.fn()} />);
    const draft = screen.getByPlaceholderText(/Type or paste tags/);
    fireEvent.change(draft, { target: { value: "hiking, outdoors" } });
    fireEvent.keyDown(draft, { key: "Enter" });
    expect(onUpdate).toHaveBeenCalledWith({
      etsy: { tags: ["Botanical", "Gift", "hiking", "outdoors"] },
    });
  });

  it("shows no tags placeholder when the list is empty", () => {
    render(
      <DetailsTab
        detail={detail({ etsy: { ...detail().etsy, tags: [] } })}
        onUpdate={vi.fn()}
        onFlush={vi.fn()}
      />,
    );
    expect(screen.getByText("No tags yet")).toBeInTheDocument();
  });

  it("shows the resolved pricing plan and price table", () => {
    render(<DetailsTab detail={detail()} onUpdate={vi.fn()} onFlush={vi.fn()} />);
    expect(screen.getByText("Plan: tee-basic")).toBeInTheDocument();
    expect(screen.getByText("349 NOK")).toBeInTheDocument();
  });
});
