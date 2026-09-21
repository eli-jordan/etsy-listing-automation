import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PlanDTO, StagePlanDTO } from "../../types";
import { BatchListingDrawer } from "./BatchListingDrawer";
import type { BatchListingState } from "./batchDeployState";

function stage(stageName: string, overrides: Partial<StagePlanDTO> = {}): StagePlanDTO {
  return {
    stage: stageName,
    will_run: false,
    changes: [],
    drift: [],
    actions: [],
    reason: null,
    blocked: null,
    snapshot: null,
    ...overrides,
  };
}

const plan: PlanDTO = {
  listing: "mountain-shirt",
  is_live: true,
  etsy_listing_id: 42,
  stage_plans: [
    stage("printify_product", {
      will_run: true,
      snapshot: {
        live: [{ size: "M", colour: "Black", price: "349 NOK" }],
        desired: [{ size: "M", colour: "Black", price: "379 NOK" }],
      },
      changes: [{ kind: "price", size: "M", color: "Black", before: "349 NOK", after: "379 NOK" }],
      actions: [
        { description: "Update product price", inputs: [], missing_outputs: [], outputs: [] },
      ],
    }),
    stage("etsy_listing", {
      will_run: true,
      snapshot: {
        live: {
          title: "Mountain shirt",
          description: "Old description",
          tags: ["mountain"],
          materials: ["cotton"],
          shop_section: null,
          shipping_profile: null,
        },
        desired: {
          title: "Mountain sunrise shirt",
          description: "New description",
          tags: ["mountain"],
          materials: ["cotton"],
          shop_section: null,
          shipping_profile: null,
        },
      },
      changes: [
        { kind: "field", path: "title", before: "Mountain shirt", after: "Mountain sunrise shirt" },
      ],
    }),
  ],
};

const listing: BatchListingState = {
  listing: "mountain-shirt",
  reviewedPlan: plan,
  plan,
  fingerprint: "fingerprint",
  planFailure: null,
  failureMessage: null,
  stale: false,
  checkingStage: null,
  stageRuntime: {},
};

describe("BatchListingDrawer", () => {
  it("composes the individual step strip, comparison, and price table", () => {
    render(
      <BatchListingDrawer
        open
        listing={listing}
        summary={{ name: "mountain-shirt", design: "bundled-grid" }}
        previewsRendered={new Set(["mountain-shirt|flat-lay|black"])}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole("dialog", { name: "mountain-shirt" })).toBeInTheDocument();
    expect(screen.getByText("Change on Etsy")).toBeInTheDocument();
    expect(screen.getByText("Title · Prices")).toBeInTheDocument();
    expect(screen.getByText("What apply will do")).toBeInTheDocument();
    expect(screen.getAllByText("On Etsy now").length).toBeGreaterThan(0);
    expect(screen.getAllByText("After apply").length).toBeGreaterThan(0);
    expect(screen.getByRole("columnheader", { name: "Difference" })).toBeInTheDocument();
    expect(screen.getByText("sunrise")).toBeInTheDocument();
  });

  it("closes on Escape or scrim click and restores focus to the opener", () => {
    const onClose = vi.fn();
    const { rerender } = render(
      <>
        <button type="button">Open mountain shirt</button>
        <BatchListingDrawer open={false} listing={listing} onClose={onClose} />
      </>,
    );
    const opener = screen.getByRole("button", { name: "Open mountain shirt" });
    opener.focus();
    rerender(
      <>
        <button type="button">Open mountain shirt</button>
        <BatchListingDrawer open listing={listing} onClose={onClose} />
      </>,
    );
    const dialog = screen.getByRole("dialog", { name: "mountain-shirt" });
    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
    expect(document.body.style.overflow).toBe("hidden");

    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
    rerender(
      <>
        <button type="button">Open mountain shirt</button>
        <BatchListingDrawer open={false} listing={listing} onClose={onClose} />
      </>,
    );
    expect(opener).toHaveFocus();
    expect(document.body.style.overflow).toBe("");

    rerender(
      <>
        <button type="button">Open mountain shirt</button>
        <BatchListingDrawer open listing={listing} onClose={onClose} />
      </>,
    );
    fireEvent.click(screen.getByRole("dialog", { name: "mountain-shirt" }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("keeps keyboard focus inside the native dialog", () => {
    render(<BatchListingDrawer open listing={listing} onClose={vi.fn()} />);

    const dialog = screen.getByRole("dialog", { name: "mountain-shirt" });
    const close = screen.getByRole("button", { name: "Close" });
    const actionSummary = screen.getByText("1 action");
    actionSummary.focus();
    fireEvent.keyDown(dialog, { key: "Tab" });

    expect(close).toHaveFocus();
  });

  it("resizes from the handle in both directions", () => {
    render(<BatchListingDrawer open listing={listing} onClose={vi.fn()} />);

    const dialog = screen.getByRole("dialog", { name: "mountain-shirt" });
    const panel = dialog.querySelector<HTMLElement>(".batch-drawer-panel");
    const handle = screen.getByRole("button", { name: "Expand drawer" });
    expect(handle).toHaveAttribute("aria-expanded", "false");
    if (panel === null) throw new Error("drawer panel is missing");

    fireEvent.click(handle);
    expect(handle).toHaveAttribute("aria-expanded", "true");
    expect(panel).toHaveClass("batch-drawer-panel--expanded");

    fireEvent.click(handle);
    vi.spyOn(panel, "getBoundingClientRect").mockReturnValue({ height: 600 } as DOMRect);
    fireEvent.pointerDown(handle, { button: 0, clientY: 400, pointerId: 1 });
    fireEvent.pointerMove(handle, { clientY: 350, pointerId: 1 });
    expect(panel).toHaveStyle({ height: "650px" });
    fireEvent.pointerMove(handle, { clientY: 300, pointerId: 1 });
    expect(panel).toHaveStyle({ height: "700px" });
    expect(handle).toHaveAttribute("aria-expanded", "true");

    fireEvent.pointerUp(handle, { clientY: 300, pointerId: 1 });
    vi.mocked(panel.getBoundingClientRect).mockReturnValue({ height: 600 } as DOMRect);
    fireEvent.pointerDown(handle, { button: 0, clientY: 400, pointerId: 2 });
    fireEvent.pointerMove(handle, { clientY: 500, pointerId: 2 });
    expect(panel).toHaveStyle({ height: "500px" });
    expect(handle).toHaveAttribute("aria-expanded", "false");
  });

  it("keeps a removed listing inspectable with a name-only fallback", () => {
    const removed: BatchListingState = {
      ...listing,
      listing: "removed-shirt",
      plan: null,
      reviewedPlan: null,
    };
    render(<BatchListingDrawer open listing={removed} onClose={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "removed-shirt", level: 3 })).toBeInTheDocument();
    expect(
      screen.getByText("The reviewed plan is no longer available for this listing."),
    ).toBeInTheDocument();
  });
});
