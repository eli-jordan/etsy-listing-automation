import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as calibrator from "../../api/calibrator";
import type { ListingDetail, TemplateSummary } from "../../types";
import { ImagesTab } from "./ImagesTab";

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

function summary(over: Partial<TemplateSummary> & { name: string }): TemplateSummary {
  return {
    kind: "colour-matrix",
    colours: ["black", "white"],
    has_config: true,
    status: "calibrated",
    status_reason: null,
    ...over,
  };
}

afterEach(() => vi.restoreAllMocks());

describe("ImagesTab", () => {
  it("lists calibrated templates but not ones still needing calibration", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([
      summary({ name: "flat-lay-01" }),
      summary({ name: "unfinished", status: "needs-calibration" }),
    ]);
    render(<ImagesTab detail={detail()} onUpdate={vi.fn()} />);
    await screen.findByText("flat-lay-01");
    expect(screen.queryByText("unfinished")).not.toBeInTheDocument();
  });

  it("expands a colour-matrix template into colour chips and adds one on click", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([summary({ name: "flat-lay-01" })]);
    const onUpdate = vi.fn();
    render(<ImagesTab detail={detail()} onUpdate={onUpdate} />);

    fireEvent.click(await screen.findByText("flat-lay-01"));
    fireEvent.click(screen.getByRole("button", { name: "black" }));

    expect(onUpdate).toHaveBeenCalledWith({
      media: [{ template: "flat-lay-01", colour: "black" }],
    });
  });

  it("adds a multiple-kind template with a single click and no colour", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([
      summary({ name: "colour-chart-01", kind: "multiple", colours: [] }),
    ]);
    const onUpdate = vi.fn();
    render(<ImagesTab detail={detail()} onUpdate={onUpdate} />);

    fireEvent.click(await screen.findByText("colour-chart-01"));
    fireEvent.click(screen.getByRole("button", { name: "+ Add" }));

    expect(onUpdate).toHaveBeenCalledWith({
      media: [{ template: "colour-chart-01", colour: null }],
    });
  });

  it("does not add the same template/colour combination twice", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([summary({ name: "flat-lay-01" })]);
    const onUpdate = vi.fn();
    render(
      <ImagesTab
        detail={detail({ media: [{ template: "flat-lay-01", colour: "black" }] })}
        onUpdate={onUpdate}
      />,
    );

    fireEvent.click(await screen.findByText("flat-lay-01"));
    fireEvent.click(screen.getByRole("button", { name: "black" }));
    expect(onUpdate).not.toHaveBeenCalled();
  });

  it("shows the reel with a position number and an Etsy-thumbnail marker on the first tile", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([]);
    const { container } = render(
      <ImagesTab
        detail={detail({
          media: [
            { template: "flat-lay-01", colour: "black" },
            { template: "flat-lay-01", colour: "white" },
          ],
        })}
        onUpdate={vi.fn()}
      />,
    );
    expect(screen.getByText("Etsy thumbnail")).toBeInTheDocument();
    const positions = Array.from(container.querySelectorAll(".rtile__pos")).map(
      (el) => el.textContent,
    );
    expect(positions).toEqual(["1", "2"]);
  });

  it("removes a reel tile when its × is clicked", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([]);
    const onUpdate = vi.fn();
    render(
      <ImagesTab
        detail={detail({ media: [{ template: "flat-lay-01", colour: "black" }] })}
        onUpdate={onUpdate}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Remove/ }));
    expect(onUpdate).toHaveBeenCalledWith({ media: [] });
  });

  it("shows the empty-reel hint when there is no media yet", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([]);
    render(<ImagesTab detail={detail()} onUpdate={vi.fn()} />);
    expect(screen.getByText(/Nothing here yet/)).toBeInTheDocument();
  });

  it("filters templates by the search box", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([
      summary({ name: "flat-lay-01" }),
      summary({ name: "detail-chest" }),
    ]);
    render(<ImagesTab detail={detail()} onUpdate={vi.fn()} />);
    await screen.findByText("flat-lay-01");

    fireEvent.change(screen.getByPlaceholderText("Search templates…"), {
      target: { value: "detail" },
    });
    expect(screen.queryByText("flat-lay-01")).not.toBeInTheDocument();
    expect(screen.getByText("detail-chest")).toBeInTheDocument();
  });
});
