import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as listingsApi from "../api/listings";
import * as runsApi from "../api/runs";
import type {
  ListingSummary,
  PlanDTO,
  RunDetail,
  RunEvent,
  RunSummary,
  StagePlanDTO,
} from "../types";
import * as runStreamModule from "./deploy/runStream";
import { BatchDeployPage } from "./BatchDeployPage";

function summary(name: string): ListingSummary {
  return {
    name,
    garment_profile: "comfort-colors-1717",
    design: "bundled-grid",
    colour_count: 1,
    status: "dirty",
    issue_counts: { block: 0, warn: 0 },
    gestures: [],
    etsy_listing_id: 42,
    printify_product_id: "product",
  };
}

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

function plan(overrides: Partial<PlanDTO> = {}): PlanDTO {
  return {
    listing: "take-a-hike",
    is_live: true,
    etsy_listing_id: 42,
    stage_plans: [stage("render", { will_run: true, reason: "new preview" })],
    ...overrides,
  };
}

function runSummary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    id: "batch-1",
    kind: "plan",
    scope: "workspace",
    listings: ["take-a-hike"],
    phase: "queued",
    seen: false,
    reviewed_run_id: null,
    created_at: "2026-09-21T10:00:00Z",
    ...overrides,
  };
}

function runDetail(overrides: Partial<RunDetail> = {}): RunDetail {
  return { ...runSummary(), events: [], ...overrides };
}

function renderPage(path = "/listings/deploy/batch-1") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/listings/deploy/:runId" element={<BatchDeployPage />} />
        <Route path="/listings" element={<p>listings page</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

function LocationProbe() {
  return <output data-testid="location">{useLocation().pathname}</output>;
}

function streamStub() {
  const handles: { lastEventId?: number; onEvent: (event: RunEvent) => void }[] = [];
  vi.spyOn(runStreamModule, "openRunStream").mockImplementation((_id, options) => {
    handles.push({
      onEvent: options.onEvent,
      ...(options.lastEventId === undefined ? {} : { lastEventId: options.lastEventId }),
    });
    return { close: vi.fn() };
  });
  return handles;
}

afterEach(() => vi.restoreAllMocks());

describe("BatchDeployPage", () => {
  beforeEach(() => {
    vi.spyOn(runsApi, "markRunSeen").mockResolvedValue(undefined);
  });

  it("replays a completed workspace plan as the authoritative review", async () => {
    vi.spyOn(runsApi, "getRun").mockResolvedValue(
      runDetail({
        phase: "ready",
        events: [
          { type: "phase", id: 1, phase: "queued" },
          {
            type: "listing_planned",
            id: 2,
            listing: "take-a-hike",
            plan: plan(),
            fingerprint: "fp-1",
          },
          { type: "phase", id: 3, phase: "ready" },
        ],
      }),
    );
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([summary("take-a-hike")]);
    const streams = streamStub();

    renderPage();

    expect(await screen.findByRole("heading", { name: "Review all changes" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /take-a-hike: 1 stage/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Apply 1 listing/ })).not.toBeDisabled();
    expect(streams).toHaveLength(0);
    await waitFor(() => expect(runsApi.markRunSeen).toHaveBeenCalledWith("batch-1"));
  });

  it("does not treat an individual or apply run as a workspace review", async () => {
    vi.spyOn(runsApi, "getRun").mockResolvedValue(
      runDetail({
        kind: "apply",
        scope: "listings",
        phase: "applying",
        events: [
          { type: "phase", id: 1, phase: "applying" },
          {
            type: "listing_planned",
            id: 2,
            listing: "take-a-hike",
            plan: plan(),
            fingerprint: "unreviewed",
          },
        ],
      }),
    );
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([summary("take-a-hike")]);

    renderPage();

    expect(
      await screen.findByText("This URL is not a workspace planning run. Return to Listings."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Review all changes" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /take-a-hike: 1 stage/ })).not.toBeInTheDocument();
  });

  it("reattaches an in-progress run after loading its recorded events", async () => {
    vi.spyOn(runsApi, "getRun").mockResolvedValue(
      runDetail({
        phase: "planning",
        events: [
          { type: "phase", id: 1, phase: "queued" },
          { type: "phase", id: 2, phase: "planning" },
        ],
      }),
    );
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([]);
    const streams = streamStub();

    renderPage();

    expect(
      await screen.findByRole("heading", { name: "Planning all listings…", level: 2 }),
    ).toBeInTheDocument();
    await waitFor(() => expect(streams).toHaveLength(1));
    expect(streams[0]?.lastEventId).toBe(2);
  });

  it("does not unlock Apply while a required preview is still missing", async () => {
    const renderPlan = plan({
      stage_plans: [
        stage("render", {
          will_run: true,
          snapshot: {
            scenes: [
              {
                scene: "front",
                template: "flat-lay",
                colour: null,
                state: "missing",
                preview: false,
              },
            ],
          },
        }),
      ],
    });
    vi.spyOn(runsApi, "getRun").mockResolvedValue(
      runDetail({
        phase: "ready",
        events: [
          { type: "phase", id: 1, phase: "queued" },
          {
            type: "listing_planned",
            id: 2,
            listing: "take-a-hike",
            plan: renderPlan,
            fingerprint: "fp-1",
          },
          { type: "phase", id: 3, phase: "previewing" },
          { type: "phase", id: 4, phase: "ready" },
        ],
      }),
    );
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([summary("take-a-hike")]);
    streamStub();

    renderPage();

    expect(
      await screen.findByText(/Preview images before applying \(0 of 1\)/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Apply 1 listing/ })).toBeDisabled();
  });

  it("creates an exact reviewed workspace apply and replaces the route with its run", async () => {
    const reviewed = runDetail({
      id: "plan-1",
      phase: "ready",
      listings: ["alpha", "bravo"],
      events: [
        { type: "phase", id: 1, phase: "queued" },
        {
          type: "listing_planned",
          id: 2,
          listing: "alpha",
          plan: plan({ listing: "alpha" }),
          fingerprint: "fp-alpha",
        },
        {
          type: "listing_planned",
          id: 3,
          listing: "bravo",
          plan: plan({ listing: "bravo" }),
          fingerprint: "fp-bravo",
        },
        { type: "phase", id: 4, phase: "ready" },
      ],
    });
    const apply = runDetail({
      id: "apply-1",
      kind: "apply",
      phase: "applying",
      listings: ["alpha", "bravo"],
      reviewed_run_id: "plan-1",
      events: [
        { type: "phase", id: 1, phase: "queued" },
        { type: "phase", id: 2, phase: "applying" },
      ],
    });
    vi.spyOn(runsApi, "getRun").mockImplementation(async (id) =>
      id === "plan-1" ? reviewed : apply,
    );
    vi.spyOn(runsApi, "createRun").mockResolvedValue({ kind: "created", run: apply });
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([summary("alpha"), summary("bravo")]);
    streamStub();

    render(
      <MemoryRouter initialEntries={["/listings/deploy/plan-1"]}>
        <Routes>
          <Route
            path="/listings/deploy/:runId"
            element={
              <>
                <BatchDeployPage />
                <LocationProbe />
              </>
            }
          />
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    const applyButton = await screen.findByRole("button", { name: /Apply 2 listings/ });
    await userEvent.click(screen.getByRole("button", { name: "alpha: 1 stage" }));
    await userEvent.click(applyButton);

    await waitFor(() =>
      expect(runsApi.createRun).toHaveBeenCalledWith({
        kind: "apply",
        scope: "workspace",
        listings: ["alpha", "bravo"],
        expect: { alpha: "fp-alpha", bravo: "fp-bravo" },
        reviewed_run_id: "plan-1",
      }),
    );
    await waitFor(() => expect(runsApi.getRun).toHaveBeenCalledWith("apply-1"));
    expect(screen.getByTestId("location")).toHaveTextContent("/listings/deploy/apply-1");
    expect(document.querySelector("dialog")).toHaveAttribute("aria-hidden", "true");
  });

  it("offers Plan again instead of Apply when the workspace is already up to date", async () => {
    vi.spyOn(runsApi, "getRun").mockResolvedValue(
      runDetail({
        phase: "ready",
        events: [
          {
            type: "listing_planned",
            id: 1,
            listing: "take-a-hike",
            plan: plan({ stage_plans: [stage("render")] }),
            fingerprint: "fp-clean",
          },
          { type: "phase", id: 2, phase: "ready" },
        ],
      }),
    );
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([summary("take-a-hike")]);
    vi.spyOn(runsApi, "createRun").mockResolvedValue({
      kind: "created",
      run: runSummary({ id: "plan-2" }),
    });

    renderPage();

    expect(await screen.findByText("Everything is up to date.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Apply/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Plan again" }));
    await waitFor(() =>
      expect(runsApi.createRun).toHaveBeenCalledWith({
        kind: "plan",
        scope: "workspace",
      }),
    );
  });

  it("overlays a reattached apply on the preserved review and refreshes listings after a result", async () => {
    const reviewed = runDetail({
      id: "plan-1",
      phase: "ready",
      listings: ["alpha", "bravo"],
      events: [
        { type: "phase", id: 1, phase: "queued" },
        {
          type: "listing_planned",
          id: 2,
          listing: "alpha",
          plan: plan({ listing: "alpha" }),
          fingerprint: "fp-alpha",
        },
        {
          type: "listing_planned",
          id: 3,
          listing: "bravo",
          plan: plan({ listing: "bravo" }),
          fingerprint: "fp-bravo",
        },
        { type: "phase", id: 4, phase: "ready" },
      ],
    });
    const apply = runDetail({
      id: "apply-1",
      kind: "apply",
      phase: "failed",
      listings: ["alpha", "bravo"],
      reviewed_run_id: "plan-1",
      events: [
        { type: "phase", id: 1, phase: "queued" },
        { type: "phase", id: 2, phase: "applying" },
        { type: "stage_applying", id: 3, listing: "alpha", stage: "render" },
        { type: "stage_applied", id: 4, listing: "alpha", stage: "render" },
        { type: "listing_failed", id: 5, listing: "bravo", message: "bravo failed" },
        { type: "phase", id: 6, phase: "failed" },
      ],
    });
    vi.spyOn(runsApi, "getRun").mockImplementation(async (id) =>
      id === "plan-1" ? reviewed : apply,
    );
    vi.spyOn(runsApi, "createRun").mockResolvedValue({
      kind: "created",
      run: runSummary({ id: "plan-2", kind: "plan", phase: "queued" }),
    });
    vi.spyOn(listingsApi, "listListings")
      .mockResolvedValueOnce([summary("alpha"), summary("bravo")])
      .mockResolvedValueOnce([summary("alpha"), summary("bravo")]);
    streamStub();

    renderPage("/listings/deploy/apply-1");

    expect(await screen.findByText(/1 listing succeeded/)).toBeInTheDocument();
    expect(screen.getByText(/1 listing failed/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Plan again" })).toBeInTheDocument();
    await waitFor(() => expect(listingsApi.listListings).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(runsApi.markRunSeen).toHaveBeenCalledWith("apply-1"));

    await userEvent.click(screen.getByRole("button", { name: "Plan again" }));
    await waitFor(() =>
      expect(runsApi.createRun).toHaveBeenCalledWith({
        kind: "plan",
        scope: "workspace",
      }),
    );
  });

  it("shows a stale result and keeps Plan again available", async () => {
    const reviewed = runDetail({
      id: "plan-1",
      phase: "ready",
      events: [
        {
          type: "listing_planned",
          id: 1,
          listing: "alpha",
          plan: plan({ listing: "alpha" }),
          fingerprint: "fp-alpha",
        },
        { type: "phase", id: 2, phase: "ready" },
      ],
    });
    const apply = runDetail({
      id: "apply-1",
      kind: "apply",
      phase: "stale",
      reviewed_run_id: "plan-1",
      events: [
        { type: "phase", id: 1, phase: "applying" },
        {
          type: "listing_failed",
          id: 2,
          listing: "alpha",
          message: "alpha changed after review",
          stale_plan: plan({ listing: "alpha" }),
        },
        { type: "phase", id: 3, phase: "stale" },
      ],
    });
    vi.spyOn(runsApi, "getRun").mockImplementation(async (id) =>
      id === "plan-1" ? reviewed : apply,
    );
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([summary("alpha")]);

    renderPage("/listings/deploy/apply-1");

    expect(await screen.findByText("Some listings became stale.")).toBeInTheDocument();
    expect(screen.getByText(/1 listing stale/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Plan again" })).toBeInTheDocument();
  });

  it("offers Try again when the workspace plan fails before review", async () => {
    vi.spyOn(runsApi, "getRun").mockResolvedValue(
      runDetail({
        id: "batch-1",
        phase: "failed",
        events: [
          { type: "phase", id: 1, phase: "planning" },
          { type: "listing_failed", id: 2, listing: "alpha", message: "service unavailable" },
          { type: "phase", id: 3, phase: "failed" },
        ],
      }),
    );
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([]);
    vi.spyOn(runsApi, "createRun").mockResolvedValue({
      kind: "created",
      run: runSummary({ id: "plan-2", kind: "plan", phase: "queued" }),
    });

    renderPage();

    expect(await screen.findByText("Planning could not finish.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() =>
      expect(runsApi.createRun).toHaveBeenCalledWith({
        kind: "plan",
        scope: "workspace",
      }),
    );
  });

  it("leaves an apply without cancelling it", async () => {
    const reviewed = runDetail({
      id: "plan-1",
      phase: "ready",
      events: [{ type: "phase", id: 1, phase: "ready" }],
    });
    const apply = runDetail({
      id: "apply-1",
      kind: "apply",
      phase: "applying",
      reviewed_run_id: "plan-1",
      events: [{ type: "phase", id: 1, phase: "applying" }],
    });
    vi.spyOn(runsApi, "getRun").mockImplementation(async (id) =>
      id === "plan-1" ? reviewed : apply,
    );
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([]);
    const cancel = vi.spyOn(runsApi, "cancelRun").mockResolvedValue(false);
    streamStub();

    renderPage("/listings/deploy/apply-1");
    await screen.findByRole("heading", { name: "Applying all changes…" });
    await userEvent.click(screen.getByRole("button", { name: "← Back to listings" }));

    expect(cancel).not.toHaveBeenCalled();
    expect(await screen.findByText("listings page")).toBeInTheDocument();
  });
});
