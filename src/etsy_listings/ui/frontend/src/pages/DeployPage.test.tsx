import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as listingsApi from "../api/listings";
import * as runsApi from "../api/runs";
import { DeployPage } from "./DeployPage";
import * as runStreamModule from "./deploy/runStream";
import type {
  ListingDetail,
  PlanDTO,
  RunDetail,
  RunEvent,
  RunSummary,
  StagePlanDTO,
} from "../types";
import {
  runDetail as makeRunDetail,
  runSummary as makeRunSummary,
  stagePlan,
  type RunSummaryOverrides,
  type StagePlanOverrides,
} from "../test/helpers";

/**
 * The route: reattach or start, composing the reducer/comparison/presentation
 * pieces (docs/deploy-changes.md decision 9). `openRunStream` is stubbed --
 * its own wire-format parsing is `runStream.test.ts`'s job -- and its
 * `onEvent` callback is captured so a test can fire the exact events a real
 * run would, in order, the same shape `deployState.test.ts` already proves
 * the reducer handles.
 */

function detail(over: Partial<ListingDetail> = {}): ListingDetail {
  return {
    garment_profile: "comfort-colors-1717",
    design: { default: "../../designs/take-a-hike.png" },
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
      variation_images: null,
      renewal: null,
      section: null,
      shipping_profile: null,
    },
    media: [],
    name: "take-a-hike",
    modified_at: "2026-09-17T10:00:00Z",
    status: "dirty",
    issues: [],
    field_errors: {},
    etsy_listing_id: 1698234512,
    printify_product_id: "abc123",
    pricing_plan_name: null,
    resolved_prices: [],
    ...over,
  };
}

function stage<Name extends StagePlanDTO["stage"]>(
  overrides: StagePlanOverrides<Name> & { stage: Name },
): Extract<StagePlanDTO, { stage: Name }> {
  const { stage: stageName, ...fields } = overrides;
  return stagePlan(stageName, fields as StagePlanOverrides<Name>);
}

function plan(stagePlans: StagePlanDTO[]): PlanDTO {
  return {
    listing: "take-a-hike",
    is_live: true,
    etsy_listing_id: 1698234512,
    stage_plans: stagePlans,
  };
}

function runSummary(over: RunSummaryOverrides = {}): RunSummary {
  return makeRunSummary({ created_at: "2026-09-17T10:00:00Z", ...over });
}

function runDetail(over: RunSummaryOverrides & { events?: RunEvent[] } = {}): RunDetail {
  return makeRunDetail({ created_at: "2026-09-17T10:00:00Z", ...over });
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/listings/take-a-hike/deploy"]}>
      <Routes>
        <Route path="/listings/:name/deploy" element={<DeployPage />} />
        <Route path="/listings/:name" element={<p>editor page</p>} />
        <Route path="/listings" element={<p>listings page</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

/** Captures the `onEvent` callback `DeployPage` registers, so a test can
 * fire events the way the real SSE stream would -- one at a time, in order. */
function stubStream() {
  const handles: { onEvent: (e: RunEvent) => void; close: ReturnType<typeof vi.fn> }[] = [];
  vi.spyOn(runStreamModule, "openRunStream").mockImplementation((_id, options) => {
    const close = vi.fn();
    handles.push({ onEvent: options.onEvent, close });
    return { close };
  });
  return handles;
}

/** The stream `stubStream` opened at position `index` -- throws rather than
 * indexing into `undefined` if a test fires an event before the component
 * has actually opened one. */
function streamAt(
  handles: { onEvent: (e: RunEvent) => void; close: ReturnType<typeof vi.fn> }[],
  index: number,
) {
  const handle = handles[index];
  if (handle === undefined) throw new Error(`no stream opened at index ${index}`);
  return handle;
}

beforeEach(() => {
  // Every test spies on the specific calls it cares about; these two are
  // fired from background effects (marking a run seen, re-deriving status
  // after apply) that most tests below don't otherwise touch, and an
  // unmocked one would hit the real `openapi-fetch` client against a
  // relative URL jsdom cannot resolve.
  vi.spyOn(runsApi, "markRunSeen").mockResolvedValue(undefined);
  vi.spyOn(listingsApi, "tryGetListing").mockResolvedValue(detail());
});

afterEach(() => vi.restoreAllMocks());

describe("DeployPage: starting fresh", () => {
  it("saves nothing pending (already the route's own job), plans, and enables Apply once ready", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(detail());
    vi.spyOn(runsApi, "currentRun").mockResolvedValue(null);
    vi.spyOn(runsApi, "createRun").mockResolvedValue({
      kind: "created",
      run: runSummary({ id: "run-1" }),
    });
    vi.spyOn(runsApi, "markRunSeen").mockResolvedValue(undefined);
    const handles = stubStream();

    renderPage();

    await waitFor(() =>
      expect(runsApi.createRun).toHaveBeenCalledWith({
        kind: "plan",
        scope: "listings",
        listings: ["take-a-hike"],
      }),
    );
    await waitFor(() => expect(handles).toHaveLength(1));

    const fullPlan = plan([
      stage({ stage: "render", will_run: true, reason: "referenced scenes changed" }),
    ]);
    streamAt(handles, 0).onEvent({ type: "phase", id: 1, phase: "planning" });
    streamAt(handles, 0).onEvent({
      type: "listing_planned",
      id: 2,
      listing: "take-a-hike",
      plan: fullPlan,
      fingerprint: "fp-1",
    });
    streamAt(handles, 0).onEvent({ type: "phase", id: 3, phase: "ready" });

    expect(await screen.findByRole("button", { name: "Apply" })).toBeEnabled();
    expect(screen.getByText("Apply will change what buyers see")).toBeInTheDocument();
    // Reaching "ready" is terminal for a plan run, so it is marked seen
    // right away (decision 9) -- waited on so the assertion is made under
    // this test's own mocks, not a later one's.
    await waitFor(() => expect(runsApi.markRunSeen).toHaveBeenCalledWith("run-1"));
  });

  it("disables Apply while blocked stages leave nothing runnable", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(detail());
    vi.spyOn(runsApi, "currentRun").mockResolvedValue(null);
    vi.spyOn(runsApi, "createRun").mockResolvedValue({
      kind: "created",
      run: runSummary({ id: "run-2" }),
    });
    const handles = stubStream();

    renderPage();
    await waitFor(() => expect(handles).toHaveLength(1));

    const blockedPlan = plan([stage({ stage: "publish", blocked: "no shop configured" })]);
    streamAt(handles, 0).onEvent({
      type: "listing_planned",
      id: 1,
      listing: "take-a-hike",
      plan: blockedPlan,
      fingerprint: "fp-2",
    });
    streamAt(handles, 0).onEvent({ type: "phase", id: 2, phase: "ready" });

    expect(await screen.findByRole("button", { name: "Apply" })).toBeDisabled();
    expect(screen.getByText("This deploy can’t go ahead yet")).toBeInTheDocument();
    await waitFor(() => expect(runsApi.markRunSeen).toHaveBeenCalledWith("run-2"));
  });
});

describe("DeployPage: reattaching", () => {
  it("rebuilds from RunDetail and keeps streaming for an active run", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(detail());
    const fullPlan = plan([stage({ stage: "render", will_run: true, reason: "x" })]);
    const detailForRun: RunDetail = runDetail({
      id: "run-3",
      kind: "plan",
      listings: ["take-a-hike"],
      phase: "planning",
      seen: false,
      events: [
        { type: "phase", id: 1, phase: "queued" },
        { type: "phase", id: 2, phase: "planning" },
      ],
    });
    vi.spyOn(runsApi, "currentRun").mockResolvedValue(
      runSummary({ id: "run-3", kind: "plan", phase: "planning" }),
    );
    vi.spyOn(runsApi, "getRun").mockResolvedValue(detailForRun);
    const handles = stubStream();

    renderPage();

    expect(await screen.findByText("Planning…")).toBeInTheDocument();
    await waitFor(() => expect(handles).toHaveLength(1));

    streamAt(handles, 0).onEvent({
      type: "listing_planned",
      id: 3,
      listing: "take-a-hike",
      plan: fullPlan,
      fingerprint: "fp-3",
    });
    streamAt(handles, 0).onEvent({ type: "phase", id: 4, phase: "ready" });

    expect(await screen.findByRole("button", { name: "Apply" })).toBeEnabled();
    await waitFor(() => expect(runsApi.markRunSeen).toHaveBeenCalledWith("run-3"));
  });

  it("shows a finished, unseen run's result without opening a stream", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(detail());
    const fullPlan = plan([stage({ stage: "render", will_run: true, reason: "x" })]);
    vi.spyOn(runsApi, "currentRun").mockResolvedValue(
      runSummary({
        id: "run-4",
        kind: "apply",
        phase: "applied",
      }),
    );
    vi.spyOn(runsApi, "getRun").mockResolvedValue(
      runDetail({
        id: "run-4",
        kind: "apply",
        phase: "applied",
        events: [
          { type: "phase", id: 1, phase: "queued" },
          {
            type: "listing_planned",
            id: 2,
            listing: "take-a-hike",
            plan: fullPlan,
            fingerprint: "fp-4",
          },
          { type: "phase", id: 3, phase: "applying" },
          { type: "stage_applying", id: 4, listing: "take-a-hike", stage: "render" },
          { type: "stage_applied", id: 5, listing: "take-a-hike", stage: "render" },
          { type: "phase", id: 6, phase: "applied" },
        ],
      }),
    );
    vi.spyOn(runsApi, "markRunSeen").mockResolvedValue(undefined);
    const handles = stubStream();

    renderPage();

    expect(await screen.findByText("Deployed.")).toBeInTheDocument();
    expect(handles).toHaveLength(0);
    await waitFor(() => expect(runsApi.markRunSeen).toHaveBeenCalledWith("run-4"), {
      timeout: 2_000,
    });
  });

  it("keeps a just-finished apply unseen when Back is clicked immediately", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(detail());
    const fullPlan = plan([stage({ stage: "render", will_run: true, reason: "x" })]);
    vi.spyOn(runsApi, "currentRun").mockResolvedValue(
      runSummary({
        id: "run-fast-apply",
        kind: "apply",
        phase: "applied",
      }),
    );
    vi.spyOn(runsApi, "getRun").mockResolvedValue(
      runDetail({
        id: "run-fast-apply",
        kind: "apply",
        phase: "applied",
        events: [
          {
            type: "listing_planned",
            id: 1,
            listing: "take-a-hike",
            plan: fullPlan,
            fingerprint: "fp-fast",
          },
          { type: "phase", id: 2, phase: "applied" },
        ],
      }),
    );
    stubStream();

    renderPage();
    expect(await screen.findByText("Deployed.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Back to editor/ }));
    await new Promise((resolve) => window.setTimeout(resolve, 800));

    expect(runsApi.markRunSeen).not.toHaveBeenCalledWith("run-fast-apply");
    expect(screen.getByText("editor page")).toBeInTheDocument();
  });
});

describe("DeployPage: Back", () => {
  it("cancels the plan run before leaving while it is still under review", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(detail());
    vi.spyOn(runsApi, "currentRun").mockResolvedValue(null);
    vi.spyOn(runsApi, "createRun").mockResolvedValue({
      kind: "created",
      run: runSummary({ id: "run-5" }),
    });
    vi.spyOn(runsApi, "cancelRun").mockResolvedValue(true);
    stubStream();

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Back/ }));

    await waitFor(() => expect(runsApi.cancelRun).toHaveBeenCalledWith("run-5"));
    expect(await screen.findByText("editor page")).toBeInTheDocument();
  });

  it("does not cancel an apply in progress, and still leaves", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(detail());
    vi.spyOn(runsApi, "currentRun").mockResolvedValue(
      runSummary({
        id: "run-6",
        kind: "apply",
        phase: "applying",
      }),
    );
    vi.spyOn(runsApi, "getRun").mockResolvedValue(
      runDetail({
        id: "run-6",
        kind: "apply",
        phase: "applying",
        events: [
          { type: "phase", id: 1, phase: "queued" },
          { type: "phase", id: 2, phase: "applying" },
        ],
      }),
    );
    const cancelSpy = vi.spyOn(runsApi, "cancelRun").mockResolvedValue(true);
    stubStream();

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Back/ }));

    expect(await screen.findByText("editor page")).toBeInTheDocument();
    expect(cancelSpy).not.toHaveBeenCalled();
  });

  it("waits for an apply click to register its run before leaving", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(detail());
    vi.spyOn(runsApi, "currentRun").mockResolvedValue(null);
    let resolveApply!: (result: runsApi.CreateRunResult) => void;
    const applyStarted = new Promise<runsApi.CreateRunResult>((resolve) => {
      resolveApply = resolve;
    });
    vi.spyOn(runsApi, "createRun")
      .mockResolvedValueOnce({
        kind: "created",
        run: runSummary({ id: "run-9" }),
      })
      .mockReturnValueOnce(applyStarted);
    const cancelSpy = vi.spyOn(runsApi, "cancelRun").mockResolvedValue(true);
    const handles = stubStream();

    renderPage();
    await waitFor(() => expect(handles).toHaveLength(1));
    streamAt(handles, 0).onEvent({
      type: "listing_planned",
      id: 1,
      listing: "take-a-hike",
      plan: plan([stage({ stage: "render", will_run: true, reason: "x" })]),
      fingerprint: "fp-9",
    });
    streamAt(handles, 0).onEvent({ type: "phase", id: 2, phase: "ready" });

    await userEvent.click(await screen.findByRole("button", { name: "Apply" }));
    await userEvent.click(screen.getByRole("button", { name: /Back/ }));
    expect(screen.queryByText("editor page")).not.toBeInTheDocument();

    resolveApply({
      kind: "created",
      run: runSummary({ id: "run-10", kind: "apply" }),
    });
    expect(await screen.findByText("editor page")).toBeInTheDocument();
    expect(cancelSpy).not.toHaveBeenCalled();
  });
});

describe("DeployPage: Apply", () => {
  it("moves stages above a collapsed approved comparison while apply is running", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(detail());
    const fullPlan = plan([stage({ stage: "publish", will_run: true, reason: "publish it" })]);
    vi.spyOn(runsApi, "currentRun").mockResolvedValue(
      runSummary({
        id: "run-applying",
        kind: "apply",
        phase: "applying",
      }),
    );
    vi.spyOn(runsApi, "getRun").mockResolvedValue(
      runDetail({
        id: "run-applying",
        kind: "apply",
        phase: "applying",
        events: [
          { type: "phase", id: 1, phase: "applying" },
          {
            type: "listing_planned",
            id: 2,
            listing: "take-a-hike",
            plan: fullPlan,
            fingerprint: "fp-applying",
          },
          {
            type: "stage_applying",
            id: 3,
            listing: "take-a-hike",
            stage: "publish",
            occurred_at: "2026-09-17T10:00:00Z",
          },
        ],
      }),
    );
    stubStream();

    renderPage();

    const stages = await screen.findByText("What apply will do");
    const disclosure = screen.getByText("View approved before-and-after comparison");
    const details = disclosure.closest("details");
    expect(details).not.toHaveAttribute("open");
    expect(
      stages.compareDocumentPosition(disclosure) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("sends the reviewed plan's fingerprint", async () => {
    vi.spyOn(listingsApi, "getListing").mockResolvedValue(detail());
    vi.spyOn(runsApi, "currentRun").mockResolvedValue(null);
    vi.spyOn(runsApi, "createRun")
      .mockResolvedValueOnce({
        kind: "created",
        run: runSummary({ id: "run-7" }),
      })
      .mockResolvedValueOnce({
        kind: "created",
        run: {
          ...runSummary({ id: "run-8", kind: "apply" }),
          phase: "queued",
        },
      });
    const handles = stubStream();

    renderPage();
    await waitFor(() => expect(handles).toHaveLength(1));

    const fullPlan = plan([stage({ stage: "render", will_run: true, reason: "x" })]);
    streamAt(handles, 0).onEvent({
      type: "listing_planned",
      id: 1,
      listing: "take-a-hike",
      plan: fullPlan,
      fingerprint: "fp-7",
    });
    streamAt(handles, 0).onEvent({ type: "phase", id: 2, phase: "ready" });
    await waitFor(() => expect(runsApi.markRunSeen).toHaveBeenCalledWith("run-7"));

    await userEvent.click(await screen.findByRole("button", { name: "Apply" }));

    expect(screen.getByText("View approved before-and-after comparison")).toBeInTheDocument();

    await waitFor(() =>
      expect(runsApi.createRun).toHaveBeenCalledWith({
        kind: "apply",
        scope: "listings",
        listings: ["take-a-hike"],
        expect: { "take-a-hike": "fp-7" },
      }),
    );
  });
});
