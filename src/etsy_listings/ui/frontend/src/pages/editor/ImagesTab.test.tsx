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
    width: 480,
    height: 576,
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

  /* A chip click on a colour already in the listing used to be a no-op, which
     is why there was a "does not add it twice" test here. It is a toggle now
     -- see "clicking a colour chip that is already in the listing takes it
     out again" below -- so duplicates are impossible by construction rather
     than by an early return. */

  it("refuses to add past Etsy's 20-image limit", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([
      summary({ name: "flat-lay-01", colours: ["black", "white"] }),
    ]);
    const onUpdate = vi.fn();
    render(
      <ImagesTab
        detail={detail({
          media: Array.from({ length: 20 }, (_, i) => ({
            template: "flat-lay-01",
            colour: `c${i}`,
          })),
        })}
        onUpdate={onUpdate}
      />,
    );

    fireEvent.click(await screen.findByText("flat-lay-01"));
    fireEvent.click(screen.getByRole("button", { name: "white" }));
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

  it("draws each reel tile in its own colour, not one photo for the whole set", async () => {
    /* `template_preview_photo` answers "any one of them", so a reel keyed on
       the template name alone drew black and ivory identically. */
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([summary({ name: "flat-lay-01" })]);
    render(
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

    expect(screen.getByAltText("flat-lay-01 · black")).toHaveAttribute(
      "src",
      "/api/templates/flat-lay-01/thumbnail?colour=black",
    );
    expect(screen.getByAltText("flat-lay-01 · white")).toHaveAttribute(
      "src",
      "/api/templates/flat-lay-01/thumbnail?colour=white",
    );
  });

  it("counts the reel against Etsy's 20-image limit", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([]);
    render(
      <ImagesTab
        detail={detail({ media: [{ template: "flat-lay-01", colour: "black" }] })}
        onUpdate={vi.fn()}
      />,
    );
    expect(screen.getByText("1 of 20")).toBeInTheDocument();
  });

  it("says what to do at the limit instead of how to reorder", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([]);
    render(
      <ImagesTab
        detail={detail({
          media: Array.from({ length: 20 }, (_, i) => ({
            template: "flat-lay-01",
            colour: `c${i}`,
          })),
        })}
        onUpdate={vi.fn()}
      />,
    );
    expect(screen.getByText(/remove one before adding another/)).toBeInTheDocument();
  });

  it("shows how many of a template's entries the listing already has", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([summary({ name: "flat-lay-01" })]);
    render(
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
    expect(await screen.findByText("2 in listing")).toBeInTheDocument();
  });

  it("clicking a colour chip that is already in the listing takes it out again", async () => {
    /* The chip is a toggle, so the reel's × is not the only way back -- and a
       chip that looks pressed but does nothing on click reads as broken. */
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([summary({ name: "flat-lay-01" })]);
    const onUpdate = vi.fn();
    render(
      <ImagesTab
        detail={detail({
          media: [
            { template: "flat-lay-01", colour: "black" },
            { template: "flat-lay-01", colour: "white" },
          ],
        })}
        onUpdate={onUpdate}
      />,
    );

    fireEvent.click(await screen.findByText("flat-lay-01"));
    fireEvent.click(screen.getByRole("button", { name: "black" }));

    expect(onUpdate).toHaveBeenCalledWith({
      media: [{ template: "flat-lay-01", colour: "white" }],
    });
  });

  it("adds every colour the listing sells but this template is missing, in one click", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([
      summary({ name: "flat-lay-01", colours: ["black", "white", "moss"] }),
    ]);
    const onUpdate = vi.fn();
    render(
      <ImagesTab
        detail={detail({
          colors: ["black", "white", "moss"],
          media: [{ template: "flat-lay-01", colour: "black" }],
        })}
        onUpdate={onUpdate}
      />,
    );

    fireEvent.click(await screen.findByText("flat-lay-01"));
    fireEvent.click(screen.getByRole("button", { name: "+ Add all 2 remaining colours" }));

    expect(onUpdate).toHaveBeenCalledWith({
      media: [
        { template: "flat-lay-01", colour: "black" },
        { template: "flat-lay-01", colour: "white" },
        { template: "flat-lay-01", colour: "moss" },
      ],
    });
  });

  it("offers no add-all when only one colour is missing", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([
      summary({ name: "flat-lay-01", colours: ["black", "white"] }),
    ]);
    render(
      <ImagesTab
        detail={detail({
          colors: ["black", "white"],
          media: [{ template: "flat-lay-01", colour: "black" }],
        })}
        onUpdate={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByText("flat-lay-01"));
    expect(screen.queryByRole("button", { name: /Add all/ })).not.toBeInTheDocument();
  });

  it("previews what the pointer is over, naming the file it would render from", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([summary({ name: "flat-lay-01" })]);
    render(<ImagesTab detail={detail({ colors: ["black"] })} onUpdate={vi.fn()} />);

    fireEvent.click(await screen.findByText("flat-lay-01"));
    fireEvent.mouseEnter(screen.getByRole("button", { name: "black" }));

    expect(screen.getByAltText("flat-lay-01 · black")).toHaveAttribute(
      "src",
      "/api/templates/flat-lay-01/thumbnail?colour=black",
    );
    expect(screen.getByText("mockup-templates/flat-lay-01/black.png")).toBeInTheDocument();
  });

  it("adds what is being previewed straight from the preview", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([summary({ name: "flat-lay-01" })]);
    const onUpdate = vi.fn();
    render(<ImagesTab detail={detail({ colors: ["black"] })} onUpdate={onUpdate} />);

    fireEvent.click(await screen.findByText("flat-lay-01"));
    fireEvent.mouseEnter(screen.getByRole("button", { name: "black" }));
    fireEvent.click(screen.getByRole("button", { name: "+ Add to listing" }));

    expect(onUpdate).toHaveBeenCalledWith({
      media: [{ template: "flat-lay-01", colour: "black" }],
    });
  });

  it("names a scene template's fixed photo, which carries no colour", async () => {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([
      summary({ name: "sizing-chart", kind: "single", colours: [] }),
    ]);
    render(<ImagesTab detail={detail()} onUpdate={vi.fn()} />);

    fireEvent.mouseEnter(await screen.findByText("sizing-chart"));

    expect(screen.getByText("mockup-templates/sizing-chart/scene.png")).toBeInTheDocument();
  });
});

describe("ImagesTab's Etsy colour-swatch toggle (PRD 56)", () => {
  function renderWith(over: Partial<ListingDetail> = {}, onUpdate = vi.fn()) {
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([
      summary({ name: "flat-lay-01", colours: ["black", "white", "moss"] }),
    ]);
    render(
      <ImagesTab
        detail={detail({
          colors: ["black", "white"],
          media: [{ template: "flat-lay-01", colour: "black" }],
          ...over,
        })}
        onUpdate={onUpdate}
      />,
    );
    return onUpdate;
  }

  it("offers the toggle only on a template the listing's media already uses", async () => {
    /* `EtsyMediaStage.desired()` refuses a variation_images template that
       `media:` does not reference, so offering it on an unused template would
       be offering a state the engine will not accept. */
    renderWith({ media: [] });
    fireEvent.click(await screen.findByText("flat-lay-01"));

    expect(screen.queryByRole("switch", { name: /Etsy colour swatches/ })).not.toBeInTheDocument();
  });

  it("turning it on names the template and fills in the colours it lacks", async () => {
    const onUpdate = renderWith();
    fireEvent.click(await screen.findByText("flat-lay-01"));

    fireEvent.click(screen.getByRole("switch", { name: /Etsy colour swatches/ }));

    expect(onUpdate).toHaveBeenCalledWith({
      media: [
        { template: "flat-lay-01", colour: "black" },
        { template: "flat-lay-01", colour: "white" },
      ],
      etsy: { variation_images: "flat-lay-01" },
    });
  });

  it("turning it off clears the field and leaves the media alone", async () => {
    const onUpdate = renderWith({
      media: [
        { template: "flat-lay-01", colour: "black" },
        { template: "flat-lay-01", colour: "white" },
      ],
      etsy: { ...detail().etsy, variation_images: "flat-lay-01" },
    });
    fireEvent.click(await screen.findByText("flat-lay-01"));

    fireEvent.click(screen.getByRole("switch", { name: /Etsy colour swatches/ }));

    expect(onUpdate).toHaveBeenCalledWith({ etsy: { variation_images: null } });
  });

  it("reports which colours the chosen template still cannot supply a swatch for", async () => {
    renderWith({
      colors: ["black", "white"],
      media: [{ template: "flat-lay-01", colour: "black" }],
      etsy: { ...detail().etsy, variation_images: "flat-lay-01" },
    });
    fireEvent.click(await screen.findByText("flat-lay-01"));

    expect(screen.getByText("1 of 2 covered")).toBeInTheDocument();
    expect(screen.getByText(/white has no image here/)).toBeInTheDocument();
  });

  it("marks the reel tiles that supply a swatch", async () => {
    const { container } = render(
      <ImagesTab
        detail={detail({
          colors: ["black"],
          media: [
            { template: "flat-lay-01", colour: "black" },
            { template: "sizing-chart", colour: null },
          ],
          etsy: { ...detail().etsy, variation_images: "flat-lay-01" },
        })}
        onUpdate={vi.fn()}
      />,
    );

    expect(container.querySelectorAll(".rtile__swatch")).toHaveLength(1);
  });
});

describe("ImagesTab's search", () => {
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
