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
    photos: [],
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
    ...over,
  };
}

beforeEach(() => {
  vi.spyOn(calibrator, "listTemplates").mockResolvedValue([]);
});

afterEach(() => vi.restoreAllMocks());

describe("VariantsTab's preview", () => {
  const profiles: GarmentProfileSummary[] = [
    {
      name: "comfort-colors-1717",
      sizes: ["S"],
      colors: { black: "dark", ivory: "light" },
      preview_template: "flat-lay-01",
    },
  ];

  function renderWithFlatLay(over: Partial<ListingDetail> = {}) {
    vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue(profiles);
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([template({ name: "flat-lay-01" })]);
    return render(
      <VariantsTab
        detail={detail({
          colors: ["black", "ivory"],
          // Preview is the garment profile's colour-matrix, not a media:
          // entry -- a new listing has not picked listing images yet.
          media: [],
          ...over,
        })}
        onUpdate={vi.fn()}
      />,
    );
  }

  it("previews the first enabled colour's real photo", async () => {
    renderWithFlatLay();
    const preview = await screen.findByAltText("black on flat-lay-01");
    expect(preview).toHaveAttribute("src", "/api/templates/flat-lay-01/photo?colour=black");
  });

  it("does not wait for the templates list before using preview_template", async () => {
    /* A new listing has no media:, and GET /api/templates can lag (it
       measures every photo). Preview is the garment profile's field; the
       list is only consulted to refuse a non-colour-matrix name. */
    vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue(profiles);
    vi.spyOn(calibrator, "listTemplates").mockReturnValue(new Promise(() => undefined));
    render(
      <VariantsTab detail={detail({ colors: ["black", "ivory"], media: [] })} onUpdate={vi.fn()} />,
    );
    const preview = await screen.findByAltText("black on flat-lay-01");
    expect(preview).toHaveAttribute("src", "/api/templates/flat-lay-01/photo?colour=black");
  });

  it("does not label the stage or overlay the colour name on it", async () => {
    /* The left column's fieldset already starts at the top of the grid; a
       "Preview" heading above the photo pushed the stage down, and the
       colour is in the image's alt (and the selected row) already. */
    const { container } = renderWithFlatLay();
    await screen.findByAltText("black on flat-lay-01");
    expect(screen.queryByText(/^Preview$/)).not.toBeInTheDocument();
    expect(container.querySelector(".preview-stage__tag")).toBeNull();
  });

  it("overlays the listing's real design once it has exactly one", async () => {
    renderWithFlatLay({ design: { default: "../../designs/take-a-hike.png" } });
    const preview = await screen.findByAltText("black on flat-lay-01");
    expect(preview).toHaveAttribute(
      "src",
      "/api/templates/flat-lay-01/design-preview?design=take-a-hike&colour=black",
    );
  });

  it("falls back to the bare photo for a multi-artwork design", async () => {
    renderWithFlatLay({
      design: {
        "on-light": "../../designs/take-a-hike-light.png",
        "on-dark": "../../designs/take-a-hike-dark.png",
      },
    });
    const preview = await screen.findByAltText("black on flat-lay-01");
    expect(preview).toHaveAttribute("src", "/api/templates/flat-lay-01/photo?colour=black");
  });

  it("shows a swatch dot sampled off the preview template", async () => {
    vi.spyOn(calibrator, "getTemplateSwatch").mockResolvedValue("#112233");
    const { container } = renderWithFlatLay();
    await screen.findByAltText("black on flat-lay-01");
    const dot = await waitFor(() => {
      const el = container.querySelector(".color-row__swatch");
      if (el === null) throw new Error("no swatch dot yet");
      return el;
    });
    expect(dot).toHaveStyle({ background: "#112233" });
  });

  it("previews whichever colour was clicked", async () => {
    renderWithFlatLay();
    await screen.findByAltText("black on flat-lay-01");

    fireEvent.click(screen.getByRole("button", { name: "Preview ivory" }));

    expect(await screen.findByAltText("ivory on flat-lay-01")).toHaveAttribute(
      "src",
      "/api/templates/flat-lay-01/photo?colour=ivory",
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

  it("explains itself when the garment profile names no colour-matrix preview", async () => {
    vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue([
      {
        name: "comfort-colors-1717",
        sizes: ["S"],
        colors: { black: "dark" },
        preview_template: null,
      },
    ]);
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([template({ name: "flat-lay-01" })]);
    render(
      <VariantsTab
        detail={detail({
          colors: ["black"],
          media: [{ template: "flat-lay-01", colour: "black" }],
        })}
        onUpdate={vi.fn()}
      />,
    );

    expect(
      await screen.findByText(/Set preview_template on the garment profile/),
    ).toBeInTheDocument();
    // media: still names a colour-matrix -- guessing from it is what made
    // preview wait on the Images tab.
    expect(screen.queryByAltText("black on flat-lay-01")).not.toBeInTheDocument();
  });

  it("ignores a preview_template that is not colour-matrix", async () => {
    vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue([
      {
        name: "comfort-colors-1717",
        sizes: ["S"],
        colors: { black: "dark" },
        preview_template: "colour-chart-01",
      },
    ]);
    vi.spyOn(calibrator, "listTemplates").mockResolvedValue([
      template({ name: "colour-chart-01", kind: "multiple", colours: [] }),
    ]);
    render(<VariantsTab detail={detail({ colors: ["black"] })} onUpdate={vi.fn()} />);

    expect(
      await screen.findByText(/Set preview_template on the garment profile/),
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

  it("dropping a colour also drops the mockups that referenced it", async () => {
    /* The bug this fixes: sending `colors` alone failed `listing.yaml`'s own
       validator server-side, which answers 200 with the listing *unchanged* --
       so the switch snapped straight back on. */
    vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue([
      { name: "comfort-colors-1717", sizes: ["S"], colors: { black: "dark", white: "light" } },
    ]);
    const onUpdate = vi.fn();
    render(
      <VariantsTab
        detail={detail({
          colors: ["black", "white"],
          media: [
            { template: "flat-lay-01", colour: "black" },
            { template: "flat-lay-01", colour: "white" },
            "../../common-media/size-guide.png",
          ],
          artwork: { white: "on-light" },
          price_overrides: { white: { S: "399 NOK" } },
        })}
        onUpdate={onUpdate}
      />,
    );

    fireEvent.click(await screen.findByRole("switch", { name: "white" }));

    expect(onUpdate).toHaveBeenCalledWith({
      colors: ["black"],
      media: [{ template: "flat-lay-01", colour: "black" }, "../../common-media/size-guide.png"],
      artwork: {},
      price_overrides: {},
    });
  });

  it("leaves the colour-keyed fields alone when a colour is only added", async () => {
    vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue([
      { name: "comfort-colors-1717", sizes: ["S"], colors: { black: "dark", white: "light" } },
    ]);
    const onUpdate = vi.fn();
    render(
      <VariantsTab
        detail={detail({
          colors: ["black"],
          media: [{ template: "flat-lay-01", colour: "black" }],
        })}
        onUpdate={onUpdate}
      />,
    );

    fireEvent.click(await screen.findByRole("switch", { name: "white" }));
    expect(onUpdate).toHaveBeenCalledWith({ colors: ["black", "white"] });
  });

  it("says so when a colour change threw listing images away", async () => {
    vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue([
      { name: "comfort-colors-1717", sizes: ["S"], colors: { black: "dark", white: "light" } },
    ]);
    render(
      <VariantsTab
        detail={detail({
          colors: ["black", "white"],
          media: [{ template: "flat-lay-01", colour: "white" }],
        })}
        onUpdate={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("switch", { name: "white" }));
    expect(screen.getByText(/Removed 1 listing image/)).toBeInTheDocument();
  });

  describe("the Dark/Light bulk buttons", () => {
    const profile = {
      name: "comfort-colors-1717",
      sizes: ["S"],
      colors: { black: "dark", navy: "dark", white: "light", ivory: "light" },
    } as const;

    function renderTab(colors: string[], onUpdate = vi.fn()) {
      vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue([
        profile as unknown as GarmentProfileSummary,
      ]);
      render(<VariantsTab detail={detail({ colors })} onUpdate={onUpdate} />);
      return onUpdate;
    }

    it("Dark enables every dark colour and disables the light ones", async () => {
      const onUpdate = renderTab(["white", "ivory"]);
      fireEvent.click(await screen.findByRole("button", { name: "Dark" }));
      expect(onUpdate).toHaveBeenCalledWith(expect.objectContaining({ colors: ["black", "navy"] }));
    });

    it("Light is its exact opposite", async () => {
      const onUpdate = renderTab(["black", "navy"]);
      fireEvent.click(await screen.findByRole("button", { name: "Light" }));
      expect(onUpdate).toHaveBeenCalledWith(
        expect.objectContaining({ colors: ["ivory", "white"] }),
      );
    });

    it("leaves colours the profile does not classify out of both", async () => {
      /* Driven by the garment profile, so a colour it has no opinion about is
         neither turned on by Dark nor by Light. */
      const onUpdate = renderTab(["forest"]);
      fireEvent.click(await screen.findByRole("button", { name: "Dark" }));
      const patch = onUpdate.mock.calls[0]?.[0] as { colors: string[] };
      expect(patch.colors).not.toContain("forest");
    });

    it("is not offered when no garment profile resolved", async () => {
      vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue([]);
      render(<VariantsTab detail={detail({ colors: ["black"] })} onUpdate={vi.fn()} />);
      await screen.findByText("black");
      expect(screen.queryByRole("button", { name: "Dark" })).not.toBeInTheDocument();
    });
  });

  it("picking a garment profile enables every colour it classifies", async () => {
    vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue([
      { name: "comfort-colors-1717", sizes: ["S"], colors: { black: "dark" } },
      { name: "gildan-5000", sizes: ["S"], colors: { black: "dark", white: "light" } },
    ]);
    const onUpdate = vi.fn();
    render(
      <VariantsTab detail={detail({ garment_profile: "", colors: [] })} onUpdate={onUpdate} />,
    );

    await waitFor(() =>
      expect(screen.getByRole("option", { name: "gildan-5000" })).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText("Garment profile"), {
      target: { value: "gildan-5000" },
    });
    expect(onUpdate).toHaveBeenCalledWith({
      garment_profile: "gildan-5000",
      colors: ["black", "white"],
    });
  });
});

describe("VariantsTab with nothing chosen yet", () => {
  it("labels the empty garment option instead of rendering a blank one", async () => {
    vi.spyOn(listingsApi, "listGarmentProfiles").mockResolvedValue([
      { name: "comfort-colors-1717", sizes: ["S"], colors: { black: "dark" } },
    ]);
    render(<VariantsTab detail={detail({ garment_profile: "", colors: [] })} onUpdate={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("Select a garment profile…")).toBeInTheDocument());
  });
});
