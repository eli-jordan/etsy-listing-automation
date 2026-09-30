import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as listingsApi from "../../api/listings";
import * as seoApi from "../../api/seo";
import type { SaveState } from "../../hooks/useAutosave";
import {
  type FakeAiRuns,
  aiRunSummary,
  fakeAiRuns,
  listingProposal,
  marketEvent,
  phaseEvent,
  proposalEvent,
  queriesEvent,
  stepEvent,
} from "../../test/aiRuns";
import { MARKET_QUERIES, marketSnapshot } from "../../test/market";
import type { ListingDetail, ListingProposal } from "../../types";
import { DetailsTab as DetailsTabView } from "./DetailsTab";
import { useAiSeoMode } from "./aiSeo/useAiSeoMode";

let runs: FakeAiRuns;

beforeEach(() => {
  localStorage.clear();
  runs = fakeAiRuns();
});

afterEach(() => {
  vi.restoreAllMocks();
});

/** What the AI run behind the button sends once it has written the
 * suggestions: the proposal, then the end of the run. */
async function runDelivers(body: ListingProposal) {
  await waitFor(() => expect(runs.streams).toHaveLength(1));
  runs.emit(proposalEvent(body), phaseEvent("done"));
}

/** The tab with AI Mode attached, exactly as `ListingEditorShell` mounts it.
 *
 * `useAiSeoMode` moved out of `DetailsTab` and up to the shell: a
 * run has to survive a tab switch, and the chain that starts one begins
 * at the design strip above the tabs. Every test below is still about what
 * the tab *does* with AI Mode, so the harness supplies the same wiring the
 * real caller does rather than a stub -- a hand-built `AiSeoMode` object
 * would test this file's idea of the hook instead of the hook. */
function DetailsTab(props: {
  detail: ListingDetail;
  onUpdate: (patch: Record<string, unknown>) => void;
  onFlush: () => void;
  save?: SaveState;
}) {
  const aiSeo = useAiSeoMode(props.detail, props.onUpdate, props.onFlush, props.save);
  return (
    <DetailsTabView
      detail={props.detail}
      onUpdate={props.onUpdate}
      onFlush={props.onFlush}
      aiSeo={aiSeo}
    />
  );
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
    gestures: [],
    description_composed: "",
    ...over,
  };
}

describe("DetailsTab for a listing template", () => {
  /* UI doc §3: Brief, Title, Tags, Description lead and AI Mode are written
     for each listing in a batch, so a listing template has none of them. */
  it("has none of the design-specific fields, and says where the lead goes", () => {
    vi.spyOn(listingsApi, "listEtsySections").mockResolvedValue({ available: false, sections: [] });
    vi.spyOn(listingsApi, "listCommonCopy").mockResolvedValue([]);
    render(
      <DetailsTabView
        kind="listing-template"
        detail={detail({ etsy: { ...detail().etsy, section: "Hiking tees" } })}
        onUpdate={vi.fn()}
        onFlush={vi.fn()}
      />,
    );

    for (const label of ["Brief", "Title", "Description Lead"]) {
      expect(screen.queryByLabelText(label)).not.toBeInTheDocument();
    }
    expect(screen.queryByText("Tags")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /AI Mode/ })).not.toBeInTheDocument();
    expect(screen.getByText("Description Body")).toBeInTheDocument();
    expect(screen.getByLabelText("Section")).toHaveValue("Hiking tees");
    expect(
      screen.getByText("Each listing's own description lead is placed above this body."),
    ).toBeInTheDocument();
  });

  it("still edits the description body", () => {
    vi.spyOn(listingsApi, "listEtsySections").mockResolvedValue({ available: false, sections: [] });
    vi.spyOn(listingsApi, "listCommonCopy").mockResolvedValue([]);
    const onUpdate = vi.fn();
    render(
      <DetailsTabView
        kind="listing-template"
        detail={detail()}
        onUpdate={onUpdate}
        onFlush={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Description body"), { target: { value: "Cotton." } });

    expect(onUpdate).toHaveBeenCalledWith({
      etsy: { description: { lead: "", text: "Cotton.", ref: null } },
    });
  });
});

describe("DetailsTab", () => {
  it("shows and edits the brief through normal autosave", () => {
    const onUpdate = vi.fn();
    const onFlush = vi.fn();
    render(
      <DetailsTab
        detail={detail({ brief: "A hiking shirt." })}
        onUpdate={onUpdate}
        onFlush={onFlush}
      />,
    );

    const brief = screen.getByRole("textbox", { name: "Brief" });
    expect(brief).toHaveValue("A hiking shirt.");
    expect(brief).toHaveAttribute(
      "placeholder",
      "Describe the design and include any exact words shown in it.",
    );
    fireEvent.change(brief, { target: { value: "A trail shirt." } });
    fireEvent.blur(brief);
    expect(onUpdate).toHaveBeenCalledWith({ brief: "A trail shirt." });
    expect(onFlush).toHaveBeenCalled();
  });

  it("renders the current title, description lead and tags", () => {
    render(
      <DetailsTab
        detail={detail({ etsy: { ...detail().etsy, title: "Take A Hike Tee" } })}
        onUpdate={vi.fn()}
        onFlush={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("Title")).toHaveValue("Take A Hike Tee");
    expect(screen.getByLabelText("Description Lead")).toHaveValue("");
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
    fireEvent.change(screen.getByLabelText("Description Lead"), {
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
    expect(screen.getByLabelText("Description Body")).toHaveTextContent("Write inline body");
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
    await userEvent.click(screen.getByLabelText("Description Body"));
    expect(
      await screen.findByRole("option", { name: "Comfort Colors care and fit" }),
    ).toBeInTheDocument();
    expect(screen.getByText("common-copy/comfort-colors.md")).toBeInTheDocument();
    expect(screen.getByText("common-copy/generic-care.md")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Generic care" })).toBeInTheDocument();
  });

  it("filters common copy by title and summary", async () => {
    vi.spyOn(listingsApi, "listCommonCopy").mockResolvedValue([
      { ref: "common-copy/comfort.md", title: "Comfort Colors", summary: "Care and fit" },
      { ref: "common-copy/shipping.md", title: "Shipping", summary: "Delivery notes" },
    ]);
    render(<DetailsTab detail={detail()} onUpdate={vi.fn()} onFlush={vi.fn()} />);

    await userEvent.click(screen.getByLabelText("Description Body"));
    const search = screen.getByRole("searchbox", { name: "Search description body sources" });
    await userEvent.type(search, "care");
    expect(screen.getByRole("option", { name: /Comfort Colors/ })).toBeInTheDocument();
    expect(screen.getByText("common-copy/comfort.md")).toBeInTheDocument();
    expect(screen.queryByText("Care and fit")).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Shipping/ })).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Write inline body" })).toBeInTheDocument();
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
    await userEvent.click(screen.getByLabelText("Description Body"));
    await userEvent.click(
      await screen.findByRole("option", { name: "Comfort Colors care and fit" }),
    );

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

  it("switching back to inline body clears any stored ref", async () => {
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

    await userEvent.click(screen.getByLabelText("Description Body"));
    await userEvent.click(screen.getByRole("option", { name: "Write inline body" }));

    expect(onUpdate).toHaveBeenCalledWith({
      etsy: { description: { lead: "A relaxed tee.", text: "", ref: null } },
    });
  });

  it("hides the inline body when a common-copy file is selected", async () => {
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
    expect(await screen.findByLabelText("Description Body")).toHaveTextContent(
      "Comfort Colors care and fit",
    );
    expect(screen.queryByLabelText("Description body")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Care and fit notes shared across every Comfort Colors listing."),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("common-copy/comfort-colors.md")).not.toBeInTheDocument();
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
    const previewLink = screen.getByRole("button", { name: "Description preview" });
    expect(screen.queryByRole("region", { name: "Description preview" })).not.toBeInTheDocument();
    fireEvent.click(previewLink);
    expect(screen.getByRole("region", { name: "Description preview" })).toHaveTextContent(
      "A relaxed tee. Printed to order. (composed server-side)",
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("region", { name: "Description preview" })).not.toBeInTheDocument();
    expect(previewLink).toHaveFocus();
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

  it("does not show garment materials in listing details", () => {
    render(
      <DetailsTab
        detail={detail({ garment_materials: ["cotton", "水性インク"] })}
        onUpdate={vi.fn()}
        onFlush={vi.fn()}
      />,
    );
    expect(screen.queryByLabelText("Materials")).not.toBeInTheDocument();
    expect(screen.queryByText("cotton")).not.toBeInTheDocument();
  });

  it("shows a section dropdown once the shop's sections are known", async () => {
    vi.spyOn(listingsApi, "listEtsySections").mockResolvedValue({
      available: true,
      sections: [
        { id: 1, title: "Tees" },
        { id: 2, title: "Hoodies" },
      ],
    });
    const onUpdate = vi.fn();
    render(
      <DetailsTab
        detail={detail({ etsy: { ...detail().etsy, section: "Tees" } })}
        onUpdate={onUpdate}
        onFlush={vi.fn()}
      />,
    );
    await screen.findByText("Hoodies");
    expect(screen.getByLabelText("Section")).toHaveValue("1");
    fireEvent.change(screen.getByLabelText("Section"), { target: { value: "2" } });
    expect(onUpdate).toHaveBeenCalledWith({ etsy: { section: "Hoodies" } });
  });

  it("creates and selects a new shop section from the dropdown", async () => {
    vi.spyOn(listingsApi, "listEtsySections").mockResolvedValue({
      available: true,
      sections: [
        { id: 1, title: "Tees" },
        { id: 2, title: "Hoodies" },
      ],
    });
    const create = vi
      .spyOn(listingsApi, "createEtsySection")
      .mockResolvedValue({ id: 3, title: "Trail Gear" });
    const onUpdate = vi.fn();
    const onFlush = vi.fn();
    const user = userEvent.setup();
    render(
      <DetailsTab
        detail={detail({ etsy: { ...detail().etsy, section: "Tees" } })}
        onUpdate={onUpdate}
        onFlush={onFlush}
      />,
    );

    await screen.findByRole("option", { name: "Hoodies" });
    await user.selectOptions(screen.getByLabelText("Section"), "create");
    await user.type(screen.getByLabelText("New section name"), "  Trail Gear  ");
    await user.click(screen.getByRole("button", { name: "Create section" }));

    expect(create).toHaveBeenCalledWith("Trail Gear");
    expect(onUpdate).toHaveBeenCalledWith({ etsy: { section: "Trail Gear" } });
    expect(onFlush).toHaveBeenCalled();
    expect(screen.queryByLabelText("New section name")).not.toBeInTheDocument();
  });

  it("falls back to a text field when no shop sections are available", async () => {
    vi.spyOn(listingsApi, "listEtsySections").mockResolvedValue({
      available: false,
      sections: [],
    });
    render(<DetailsTab detail={detail()} onUpdate={vi.fn()} onFlush={vi.fn()} />);
    const field = await screen.findByLabelText("Section");
    expect(field.tagName).toBe("INPUT");
  });

  it("can create the first section in an available empty shop", async () => {
    vi.spyOn(listingsApi, "listEtsySections").mockResolvedValue({
      available: true,
      sections: [],
    });
    render(<DetailsTab detail={detail()} onUpdate={vi.fn()} onFlush={vi.fn()} />);

    await waitFor(() => expect(screen.getByLabelText("Section").tagName).toBe("SELECT"));
    expect(screen.getByRole("option", { name: "Create new section…" })).toBeInTheDocument();
  });
});

describe("DetailsTab AI Mode", () => {
  function readyDetail(over: Partial<ListingDetail> = {}): ListingDetail {
    return detail({
      design: { default: "designs/take-a-hike.png" },
      brief: "A relaxed hiking tee.",
      garment_product_type: "tee",
      garment_brand: "Comfort Colors",
      garment_model: "1717",
      ...over,
    });
  }

  const proposal = () => listingProposal();

  it("shows disabled AI Mode without a design and brief", () => {
    render(<DetailsTab detail={detail()} onUpdate={vi.fn()} onFlush={vi.fn()} />);
    expect(screen.getByRole("button", { name: /AI Mode/i })).toBeDisabled();
  });

  it("asks readiness with an empty brief, and again after the listing changes", async () => {
    const readiness = vi
      .spyOn(seoApi, "getSeoReadiness")
      .mockResolvedValueOnce({
        ready: false,
        reason: "prompts/brief.md is missing",
        batch_pending: false,
        deploying: false,
      })
      .mockResolvedValueOnce({ ready: true, batch_pending: false, deploying: false });
    const { rerender } = render(
      <DetailsTab detail={readyDetail({ brief: "" })} onUpdate={vi.fn()} onFlush={vi.fn()} />,
    );

    await waitFor(() => expect(readiness).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("button", { name: /AI Mode/i })).toBeDisabled();

    rerender(
      <DetailsTab
        detail={readyDetail({ modified_at: "2026-09-17T10:00:01Z" })}
        onUpdate={vi.fn()}
        onFlush={vi.fn()}
      />,
    );
    await waitFor(() => expect(screen.getByRole("button", { name: /AI Mode/i })).toBeEnabled());
    expect(readiness).toHaveBeenCalledTimes(2);
  });

  it("rechecks readiness after save even when modified_at is unchanged", async () => {
    const readiness = vi
      .spyOn(seoApi, "getSeoReadiness")
      .mockResolvedValueOnce({
        ready: false,
        reason: "the listing brief is empty",
        batch_pending: false,
        deploying: false,
      })
      .mockResolvedValueOnce({ ready: true, batch_pending: false, deploying: false });
    const current = readyDetail();
    const { rerender } = render(
      <DetailsTab
        detail={current}
        onUpdate={vi.fn()}
        onFlush={vi.fn()}
        save={{ kind: "saved", savedAt: 1 }}
      />,
    );
    await waitFor(() => expect(readiness).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("button", { name: /AI Mode/i })).toBeDisabled();

    rerender(
      <DetailsTab
        detail={current}
        onUpdate={vi.fn()}
        onFlush={vi.fn()}
        save={{ kind: "saving" }}
      />,
    );
    rerender(
      <DetailsTab
        detail={current}
        onUpdate={vi.fn()}
        onFlush={vi.fn()}
        save={{ kind: "saved", savedAt: 2 }}
      />,
    );
    await waitFor(() => expect(screen.getByRole("button", { name: /AI Mode/i })).toBeEnabled());
    expect(readiness).toHaveBeenCalledTimes(2);
  });

  it("keeps AI Mode disabled when the readiness endpoint says no", async () => {
    vi.spyOn(seoApi, "getSeoReadiness").mockResolvedValue({
      ready: false,
      batch_pending: false,
      deploying: false,
    });
    render(<DetailsTab detail={readyDetail()} onUpdate={vi.fn()} onFlush={vi.fn()} />);

    await waitFor(() => expect(seoApi.getSeoReadiness).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: /AI Mode/i })).toBeDisabled();
  });

  it("renders AI Mode once the readiness endpoint says ready", async () => {
    vi.spyOn(seoApi, "getSeoReadiness").mockResolvedValue({
      ready: true,
      batch_pending: false,
      deploying: false,
    });

    render(<DetailsTab detail={readyDetail()} onUpdate={vi.fn()} onFlush={vi.fn()} />);

    expect(await screen.findByRole("button", { name: /AI Mode/i })).toBeEnabled();
  });

  it("reveals all three drawers after a successful request and focuses the first title option", async () => {
    vi.spyOn(seoApi, "getSeoReadiness").mockResolvedValue({
      ready: true,
      batch_pending: false,
      deploying: false,
    });
    const body = proposal();

    render(<DetailsTab detail={readyDetail()} onUpdate={vi.fn()} onFlush={vi.fn()} />);
    const aiModeButton = await screen.findByRole("button", { name: /AI Mode/i });
    await userEvent.click(aiModeButton);
    await runDelivers(body);

    expect(await screen.findByRole("region", { name: "title AI suggestions" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "tag AI suggestions" })).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "description lead AI suggestions" }),
    ).toBeInTheDocument();

    await waitFor(() => expect(screen.getByRole("button", { name: /Title A/ })).toHaveFocus());
  });

  it("returns focus to the AI Mode button once the last drawer resolves", async () => {
    vi.spyOn(seoApi, "getSeoReadiness").mockResolvedValue({
      ready: true,
      batch_pending: false,
      deploying: false,
    });
    const body = proposal();

    render(<DetailsTab detail={readyDetail()} onUpdate={vi.fn()} onFlush={vi.fn()} />);
    const aiModeButton = await screen.findByRole("button", { name: /AI Mode/i });
    await userEvent.click(aiModeButton);
    await runDelivers(body);
    await screen.findByRole("region", { name: "title AI suggestions" });

    await userEvent.click(screen.getByRole("button", { name: /Title A/ }));
    await userEvent.click(
      within(screen.getByRole("region", { name: "tag AI suggestions" })).getByRole("button", {
        name: /close/i,
      }),
    );
    await userEvent.click(screen.getByRole("button", { name: /Lead A/ }));

    await waitFor(() => expect(aiModeButton).toHaveFocus());
  });

  it("applies the chosen title through the normal autosave path", async () => {
    vi.spyOn(seoApi, "getSeoReadiness").mockResolvedValue({
      ready: true,
      batch_pending: false,
      deploying: false,
    });
    const onUpdate = vi.fn();
    const onFlush = vi.fn();

    render(<DetailsTab detail={readyDetail()} onUpdate={onUpdate} onFlush={onFlush} />);
    await userEvent.click(await screen.findByRole("button", { name: /AI Mode/i }));
    await runDelivers(proposal());
    await screen.findByRole("region", { name: "title AI suggestions" });

    await userEvent.click(screen.getByRole("button", { name: /Title B/ }));

    expect(onUpdate).toHaveBeenCalledWith({ etsy: { title: "Title B" } });
    expect(onFlush).toHaveBeenCalled();
  });

  it("keeps an out-of-date proposal's choices usable and names what changed", async () => {
    vi.spyOn(seoApi, "getSeoReadiness").mockResolvedValue({
      ready: true,
      batch_pending: false,
      deploying: false,
    });
    runs.cached.proposal = listingProposal({
      stale: { is_stale: true, reasons: ["brief edited since"] },
    });
    const onUpdate = vi.fn();

    render(<DetailsTab detail={readyDetail()} onUpdate={onUpdate} onFlush={vi.fn()} />);
    const drawer = await screen.findByRole("region", { name: "title AI suggestions" });

    expect(
      within(drawer).getByText("Out of date: brief edited since. Still usable"),
    ).toBeInTheDocument();
    await userEvent.click(within(drawer).getByRole("button", { name: /Title B/ }));
    expect(onUpdate).toHaveBeenCalledWith({ etsy: { title: "Title B" } });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens only the sections of the cached proposal the seller has not resolved", async () => {
    vi.spyOn(seoApi, "getSeoReadiness").mockResolvedValue({
      ready: true,
      batch_pending: false,
      deploying: false,
    });
    runs.cached.proposal = listingProposal({
      resolution: { title: "accepted", tags: "dismissed", lead: "pending" },
    });

    render(<DetailsTab detail={readyDetail()} onUpdate={vi.fn()} onFlush={vi.fn()} />);

    expect(
      await screen.findByRole("region", { name: "description lead AI suggestions" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "title AI suggestions" })).toBeNull();
    expect(screen.queryByRole("region", { name: "tag AI suggestions" })).toBeNull();
  });

  it("shows a Try again failure state without changing any listing field", async () => {
    vi.spyOn(seoApi, "getSeoReadiness").mockResolvedValue({
      ready: true,
      batch_pending: false,
      deploying: false,
    });
    const onUpdate = vi.fn();

    render(<DetailsTab detail={readyDetail()} onUpdate={onUpdate} onFlush={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: /AI Mode/i }));
    await waitFor(() => expect(runs.streams).toHaveLength(1));
    runs.emit(phaseEvent("failed"));

    expect(await screen.findByText(/couldn.t generate/i)).toBeInTheDocument();
    expect(onUpdate).not.toHaveBeenCalled();
  });
});

describe("DetailsTab top listings panel", () => {
  const withDesign = () =>
    detail({ design: { default: "designs/take-a-hike.png" }, brief: "A relaxed hiking tee." });

  function fieldset() {
    return screen.getByRole("group", { name: "Listing details" });
  }

  it("keeps the fields at their own width when there is no search to show", async () => {
    render(<DetailsTab detail={withDesign()} onUpdate={vi.fn()} onFlush={vi.fn()} />);

    await waitFor(() => expect(runs.market).toHaveBeenCalledWith("take-a-hike"));
    expect(screen.queryByRole("complementary", { name: "Similar Etsy Listings" })).toBeNull();
    expect(fieldset().closest(".mkt-layout")).toBeNull();
  });

  it("puts the last search beside the fields", async () => {
    runs.market.mockResolvedValue(marketSnapshot());

    render(<DetailsTab detail={withDesign()} onUpdate={vi.fn()} onFlush={vi.fn()} />);

    const panel = await screen.findByRole("complementary", { name: "Similar Etsy Listings" });
    const layout = fieldset().closest(".mkt-layout");
    expect(layout?.children).toHaveLength(2);
    expect(layout?.children[0]).toHaveClass("details-tab");
    expect(layout?.children[0]).toContainElement(fieldset());
    expect(layout?.children[1]).toBe(panel);
  });

  it("keeps the seller's place in the fields when the panel appears", async () => {
    runs.find.mockResolvedValue(aiRunSummary());
    render(<DetailsTab detail={withDesign()} onUpdate={vi.fn()} onFlush={vi.fn()} />);
    await waitFor(() => expect(runs.streams).toHaveLength(1));
    const title = screen.getByLabelText("Title");
    title.focus();

    runs.emit(stepEvent("market", "active"));

    expect(screen.getByRole("complementary", { name: "Similar Etsy Listings" })).toBeVisible();
    expect(screen.getByLabelText("Title")).toBe(title);
    expect(title).toHaveFocus();
  });

  it("shows research as the run does it, and what it found", async () => {
    runs.find.mockResolvedValue(aiRunSummary());
    render(<DetailsTab detail={withDesign()} onUpdate={vi.fn()} onFlush={vi.fn()} />);
    await waitFor(() => expect(runs.streams).toHaveLength(1));

    runs.emit(stepEvent("market", "active"), queriesEvent(MARKET_QUERIES));

    const panel = screen.getByRole("complementary", { name: "Similar Etsy Listings" });
    expect(panel).toHaveTextContent("Searching Etsy for “retro sunset hiking shirt”");

    runs.emit(marketEvent(marketSnapshot({ found: 31 })), stepEvent("market", "done"));

    expect(panel).toHaveTextContent("12 scored from 31 found");
  });

  it("ticks the phrases the pending suggestions use", async () => {
    runs.market.mockResolvedValue(marketSnapshot());
    runs.find.mockResolvedValue(aiRunSummary());
    const user = userEvent.setup();
    render(<DetailsTab detail={withDesign()} onUpdate={vi.fn()} onFlush={vi.fn()} />);
    const panel = await screen.findByRole("complementary", { name: "Similar Etsy Listings" });
    await user.click(within(panel).getByRole("tab", { name: "Phrases" }));
    expect(within(panel).queryByLabelText("In your suggestions")).toBeNull();

    await waitFor(() => expect(runs.streams).toHaveLength(1));
    const suggested = listingProposal();
    runs.emit(
      proposalEvent({
        ...suggested,
        proposal: { ...suggested.proposal, titles: ["Retro Hiking Shirt", "Title B", "Title C"] },
      }),
    );

    await waitFor(() =>
      expect(within(panel).getAllByLabelText("In your suggestions")).toHaveLength(1),
    );
    const [ticked] = within(panel).getAllByRole("listitem");
    expect(ticked).toHaveTextContent("retro hiking shirt");
    expect(ticked).toContainElement(within(panel).getByLabelText("In your suggestions"));
  });
});
