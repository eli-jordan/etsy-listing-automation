import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as listingsApi from "../../api/listings";
import type { ListingDetail } from "../../types";
import { DetailsTab } from "./DetailsTab";

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
      tags: ["Botanical", "Gift"],
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

describe("DetailsTab", () => {
  it("renders the current title, description lead and tags", () => {
    render(
      <DetailsTab
        detail={detail({ etsy: { ...detail().etsy, title: "Take A Hike Tee" } })}
        onUpdate={vi.fn()}
        onFlush={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("Title")).toHaveValue("Take A Hike Tee");
    expect(screen.getByLabelText("Description lead")).toHaveValue("");
    expect(screen.getByText("Botanical")).toBeInTheDocument();
    expect(screen.getByText("Gift")).toBeInTheDocument();
  });

  it("typing in the description lead patches the structured value, preserving the body", () => {
    const onUpdate = vi.fn();
    render(
      <DetailsTab
        detail={detail({
          etsy: {
            ...detail().etsy,
            description: { lead: "", text: "Printed to order.", ref: null },
          },
        })}
        onUpdate={onUpdate}
        onFlush={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Description lead"), {
      target: { value: "A relaxed tee." },
    });
    expect(onUpdate).toHaveBeenCalledWith({
      etsy: { description: { lead: "A relaxed tee.", text: "Printed to order.", ref: null } },
    });
  });

  it("defaults the body source to inline and shows the stored text", () => {
    render(
      <DetailsTab
        detail={detail({
          etsy: {
            ...detail().etsy,
            description: { lead: "", text: "Printed to order.", ref: null },
          },
        })}
        onUpdate={vi.fn()}
        onFlush={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("Description body source")).toHaveValue("inline");
    expect(screen.getByLabelText("Description body")).toHaveValue("Printed to order.");
  });

  it("typing the inline body patches the structured value, preserving the lead", () => {
    const onUpdate = vi.fn();
    render(
      <DetailsTab
        detail={detail({
          etsy: { ...detail().etsy, description: { lead: "A relaxed tee.", text: "", ref: null } },
        })}
        onUpdate={onUpdate}
        onFlush={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Description body"), {
      target: { value: "Printed to order." },
    });
    expect(onUpdate).toHaveBeenCalledWith({
      etsy: {
        description: { lead: "A relaxed tee.", text: "Printed to order.", ref: null },
      },
    });
  });

  it("offers every common-copy file as a body-source option", async () => {
    vi.spyOn(listingsApi, "listCommonCopy").mockResolvedValue([
      { ref: "common-copy/comfort-colors.md", title: "Comfort Colors care and fit" },
      { ref: "common-copy/generic-care.md", title: "Generic care" },
    ]);
    render(<DetailsTab detail={detail()} onUpdate={vi.fn()} onFlush={vi.fn()} />);
    expect(
      await screen.findByRole("option", { name: "Comfort Colors care and fit" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Generic care" })).toBeInTheDocument();
  });

  it("selecting a common-copy file sets the ref and clears any inline text", async () => {
    vi.spyOn(listingsApi, "listCommonCopy").mockResolvedValue([
      { ref: "common-copy/comfort-colors.md", title: "Comfort Colors care and fit" },
    ]);
    const onUpdate = vi.fn();
    render(
      <DetailsTab
        detail={detail({
          etsy: {
            ...detail().etsy,
            description: { lead: "A relaxed tee.", text: "Printed to order.", ref: null },
          },
        })}
        onUpdate={onUpdate}
        onFlush={vi.fn()}
      />,
    );
    await screen.findByRole("option", { name: "Comfort Colors care and fit" });

    fireEvent.change(screen.getByLabelText("Description body source"), {
      target: { value: "common-copy/comfort-colors.md" },
    });

    expect(onUpdate).toHaveBeenCalledWith({
      etsy: {
        description: {
          lead: "A relaxed tee.",
          text: null,
          ref: "common-copy/comfort-colors.md",
        },
      },
    });
  });

  it("switching back to inline body clears any stored ref", () => {
    const onUpdate = vi.fn();
    render(
      <DetailsTab
        detail={detail({
          etsy: {
            ...detail().etsy,
            description: {
              lead: "A relaxed tee.",
              text: null,
              ref: "common-copy/comfort-colors.md",
            },
          },
        })}
        onUpdate={onUpdate}
        onFlush={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Description body source"), {
      target: { value: "inline" },
    });

    expect(onUpdate).toHaveBeenCalledWith({
      etsy: { description: { lead: "A relaxed tee.", text: "", ref: null } },
    });
  });

  it("shows the selected common-copy file's title and summary", async () => {
    vi.spyOn(listingsApi, "listCommonCopy").mockResolvedValue([
      {
        ref: "common-copy/comfort-colors.md",
        title: "Comfort Colors care and fit",
        summary: "Care and fit notes shared across every Comfort Colors listing.",
      },
    ]);
    render(
      <DetailsTab
        detail={detail({
          etsy: {
            ...detail().etsy,
            description: { lead: "", text: null, ref: "common-copy/comfort-colors.md" },
          },
        })}
        onUpdate={vi.fn()}
        onFlush={vi.fn()}
      />,
    );
    await screen.findByRole("option", { name: "Comfort Colors care and fit" });
    expect(
      screen.getByText("Comfort Colors care and fit", { selector: ".common-copy-meta__title" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Care and fit notes shared across every Comfort Colors listing."),
    ).toBeInTheDocument();
    expect(screen.getByText("common-copy/comfort-colors.md")).toBeInTheDocument();
  });

  it("shows a block issue for a description reference that will not resolve", () => {
    render(
      <DetailsTab
        detail={detail({
          etsy: {
            ...detail().etsy,
            description: { lead: "A relaxed tee.", text: null, ref: "common-copy/missing.md" },
          },
          issues: [
            {
              severity: "block",
              tab: "details",
              where: "Listing Details › Description",
              message: "'common-copy/missing.md': file not found",
            },
          ],
        })}
        onUpdate={vi.fn()}
        onFlush={vi.fn()}
      />,
    );
    expect(screen.getByText("'common-copy/missing.md': file not found")).toBeInTheDocument();
  });

  it("shows the lead-required issue that blocks deployment while the lead is empty", () => {
    render(
      <DetailsTab
        detail={detail({
          issues: [
            {
              severity: "block",
              tab: "details",
              where: "Listing Details › Description",
              message:
                "etsy.description.lead is empty. The lead is the opening paragraph a shopper reads, and deployment is blocked until it is set.",
            },
          ],
        })}
        onUpdate={vi.fn()}
        onFlush={vi.fn()}
      />,
    );
    expect(screen.getByText(/deployment is blocked until it is set/)).toBeInTheDocument();
  });

  it("renders the server-composed description without re-joining lead and body itself", () => {
    render(
      <DetailsTab
        detail={detail({
          etsy: {
            ...detail().etsy,
            description: { lead: "A relaxed tee.", text: "Printed to order.", ref: null },
          },
          // Deliberately not what a naive `${lead}\n\n${text}` join would
          // produce -- this proves the preview renders the server's own
          // value rather than recomputing it.
          description_composed: "A relaxed tee. Printed to order. (composed server-side)",
        })}
        onUpdate={vi.fn()}
        onFlush={vi.fn()}
      />,
    );
    expect(
      screen.getByText("A relaxed tee. Printed to order. (composed server-side)"),
    ).toBeInTheDocument();
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

  it("counts the title against Etsy's own 140-character limit", () => {
    /* The limit is Etsy's and the server refuses past it, so the counter is
       what stops a long title being typed blind and rejected on save. */
    render(
      <DetailsTab
        detail={detail({ etsy: { ...detail().etsy, title: "Take A Hike Tee" } })}
        onUpdate={vi.fn()}
        onFlush={vi.fn()}
      />,
    );
    expect(screen.getByText("15 / 140")).toBeInTheDocument();
  });

  it("counts the tags against Etsy's 13-tag limit", () => {
    render(<DetailsTab detail={detail()} onUpdate={vi.fn()} onFlush={vi.fn()} />);
    expect(screen.getByText("2 / 13")).toBeInTheDocument();
  });

  it("counts an empty title as zero, not as a sentinel to hide", () => {
    render(<DetailsTab detail={detail()} onUpdate={vi.fn()} onFlush={vi.fn()} />);
    expect(screen.getByText("0 / 140")).toBeInTheDocument();
  });

  it("shows garment materials as read-only text", () => {
    const onUpdate = vi.fn();
    render(
      <DetailsTab
        detail={detail({ garment_materials: ["cotton", "水性インク"] })}
        onUpdate={onUpdate}
        onFlush={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("Materials")).toHaveValue("cotton, 水性インク");
    expect(screen.getByLabelText("Materials")).toHaveAttribute("readonly");
    expect(onUpdate).not.toHaveBeenCalled();
  });

  it("shows the resolved pricing plan and price table", async () => {
    vi.spyOn(listingsApi, "listPricingPlans").mockResolvedValue([
      {
        name: "tee-basic",
        garment_profile: "comfort-colors-1717",
        compatible: true,
        ref: "../../pricing-plans/tee-basic.yaml",
      },
    ]);
    render(
      <DetailsTab
        detail={detail({ pricing_plan: "../../pricing-plans/tee-basic.yaml" })}
        onUpdate={vi.fn()}
        onFlush={vi.fn()}
      />,
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Plan")).toHaveValue("../../pricing-plans/tee-basic.yaml"),
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
        ref: "../../pricing-plans/tee-basic.yaml",
      },
      {
        name: "tee-premium",
        garment_profile: "comfort-colors-1717",
        compatible: true,
        ref: "../../pricing-plans/tee-premium.yaml",
      },
    ]);
    render(
      <DetailsTab
        detail={detail({ pricing_plan: "../../pricing-plans/tee-basic.yaml" })}
        onUpdate={onUpdate}
        onFlush={onFlush}
      />,
    );
    await screen.findByText("tee-premium");
    fireEvent.change(screen.getByLabelText("Plan"), {
      target: { value: "../../pricing-plans/tee-premium.yaml" },
    });
    expect(onUpdate).toHaveBeenCalledWith({ pricing_plan: "../../pricing-plans/tee-premium.yaml" });
    expect(onFlush).toHaveBeenCalled();
  });

  it("editing a size's price writes a per-size override", async () => {
    const onUpdate = vi.fn();
    render(<DetailsTab detail={detail()} onUpdate={onUpdate} onFlush={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Price for size S"), { target: { value: "399" } });
    expect(onUpdate).toHaveBeenCalledWith({ prices: { S: "399 NOK" } });
  });

  it("shows a section dropdown once the shop's sections are known", async () => {
    vi.spyOn(listingsApi, "listEtsySections").mockResolvedValue([
      { id: 1, title: "Tees" },
      { id: 2, title: "Hoodies" },
    ]);
    const onUpdate = vi.fn();
    render(
      <DetailsTab
        detail={detail({ etsy: { ...detail().etsy, section: "Tees" } })}
        onUpdate={onUpdate}
        onFlush={vi.fn()}
      />,
    );
    await screen.findByText("Hoodies");
    expect(screen.getByLabelText("Section")).toHaveValue("Tees");
    fireEvent.change(screen.getByLabelText("Section"), { target: { value: "Hoodies" } });
    expect(onUpdate).toHaveBeenCalledWith({ etsy: { section: "Hoodies" } });
  });

  it("falls back to a text field when no shop sections are available", async () => {
    vi.spyOn(listingsApi, "listEtsySections").mockResolvedValue([]);
    render(<DetailsTab detail={detail()} onUpdate={vi.fn()} onFlush={vi.fn()} />);
    const field = await screen.findByLabelText("Section");
    expect(field.tagName).toBe("INPUT");
  });
});

describe("DetailsTab with no garment profile chosen", () => {
  it("does not claim every plan is for a different garment", async () => {
    vi.spyOn(listingsApi, "listPricingPlans").mockResolvedValue([
      { name: "tee-basic", garment_profile: "comfort-colors-1717", compatible: false, ref: "r" },
    ]);
    render(
      <DetailsTab detail={detail({ garment_profile: "" })} onUpdate={vi.fn()} onFlush={vi.fn()} />,
    );

    const option = await screen.findByRole("option", { name: "tee-basic" });
    expect(option).toBeInTheDocument();
    expect(screen.queryByText(/different garment/)).toBeNull();
  });
});
