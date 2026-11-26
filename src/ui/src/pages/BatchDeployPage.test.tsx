import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as batchesApi from "../api/batches";
import type { BatchDetail } from "../api/batches";
import * as listingsApi from "../api/listings";
import * as runsApi from "../api/runs";
import { MARK_SEEN_GRACE_MS } from "./deploy/runPhases";
import { controlledClock } from "../test/clock";
import type {
  ListingSummary,
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

function stage<Name extends StagePlanDTO["stage"]>(
  stageName: Name,
  overrides: StagePlanOverrides<Name> = {},
): Extract<StagePlanDTO, { stage: Name }> {
  return stagePlan(stageName, overrides);
}

function plan(overrides: Partial<PlanDTO> = {}): PlanDTO {
  return {
    listing: "take-a-hike",
    is_live: true,
    etsy_listing_id: 42,
    publishable: false,
    stage_plans: [stage("render", { will_run: true, reason: "new preview" })],
    ...overrides,
  };
}

function runSummary(overrides: RunSummaryOverrides = {}): RunSummary {
  return makeRunSummary({ id: "batch-1", scope: "workspace", ...overrides });
}

function runDetail(overrides: RunSummaryOverrides & { events?: RunEvent[] } = {}): RunDetail {
  return makeRunDetail({ id: "batch-1", scope: "workspace", ...overrides });
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
                scene_hash: "a".repeat(64),
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
        publish: false,
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
        publish: false,
      }),
    );
  });

  it("reviews a listing batch's run on the same page, applying and planning again by batch", async () => {
    const reviewed = runDetail({
      id: "plan-1",
      scope: "batch",
      batch_id: "b1",
      phase: "ready",
      listings: ["alpha"],
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
    vi.spyOn(runsApi, "getRun").mockResolvedValue(reviewed);
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([summary("alpha")]);
    vi.spyOn(batchesApi, "getBatch").mockResolvedValue({ label: "Autumn drop" } as BatchDetail);
    const create = vi.spyOn(runsApi, "createRun").mockRejectedValue(new Error("refused"));

    render(
      <MemoryRouter initialEntries={["/listings/deploy/plan-1"]}>
        <Routes>
          <Route path="/listings/deploy/:runId" element={<BatchDeployPage />} />
          <Route path="/batches/:id" element={<p>batch page</p>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Review batch changes" })).toBeVisible();
    expect(await screen.findByText(/Autumn drop/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: /Apply 1 listing/ }));
    await waitFor(() =>
      expect(create).toHaveBeenCalledWith({
        kind: "apply",
        scope: "batch",
        batch_id: "b1",
        listings: ["alpha"],
        expect: { alpha: "fp-alpha" },
        reviewed_run_id: "plan-1",
        publish: false,
      }),
    );
    expect(await screen.findByText("Could not start the reviewed batch apply.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "← Back to batch" }));
    expect(await screen.findByText("batch page")).toBeInTheDocument();
  });

  it("plans a listing batch again by its batch", async () => {
    vi.spyOn(runsApi, "getRun").mockResolvedValue(
      runDetail({
        scope: "batch",
        batch_id: "b1",
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
    vi.spyOn(batchesApi, "getBatch").mockResolvedValue({ label: "Autumn drop" } as BatchDetail);
    vi.spyOn(runsApi, "createRun").mockResolvedValue({
      kind: "created",
      run: runSummary({ id: "plan-2", scope: "batch", batch_id: "b1" }),
    });

    renderPage();

    expect(await screen.findByText("The batch plan found no changes to apply.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Plan again" }));
    await waitFor(() =>
      expect(runsApi.createRun).toHaveBeenCalledWith({
        kind: "plan",
        scope: "batch",
        batch_id: "b1",
        publish: false,
      }),
    );
  });

  it("overlays a reattached apply on the preserved review and refreshes listings after a result", async () => {
    const clock = controlledClock();
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
    expect(runsApi.markRunSeen).not.toHaveBeenCalledWith("apply-1");
    await clock.advance(MARK_SEEN_GRACE_MS);
    expect(runsApi.markRunSeen).toHaveBeenCalledWith("apply-1");

    await clock.user.click(screen.getByRole("button", { name: "Plan again" }));
    await waitFor(() =>
      expect(runsApi.createRun).toHaveBeenCalledWith({
        kind: "plan",
        scope: "workspace",
        publish: false,
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
        publish: false,
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

  it("keeps a just-finished workspace apply unseen when Back is clicked immediately", async () => {
    const clock = controlledClock();
    // Reproduces the race behind the flaky
    // test_batch_apply_leaves_reattaches_and_continues_after_stale_listing
    // browser test: handleApply's own re-navigate to this apply run's URL
    // can attach here already terminal, and an immediate Back click must not
    // let the mark-seen effect beat it -- otherwise Listings loses the
    // "View batch result" affordance entirely.
    const reviewed = runDetail({
      id: "plan-1",
      phase: "ready",
      events: [{ type: "phase", id: 1, phase: "ready" }],
    });
    const apply = runDetail({
      id: "apply-fast",
      kind: "apply",
      phase: "stale",
      reviewed_run_id: "plan-1",
      events: [
        { type: "phase", id: 1, phase: "applying" },
        {
          type: "listing_failed",
          id: 2,
          listing: "take-a-hike",
          message: "take-a-hike changed after review",
          stale_plan: plan(),
        },
        { type: "phase", id: 3, phase: "stale" },
      ],
    });
    vi.spyOn(runsApi, "getRun").mockImplementation(async (id) =>
      id === "plan-1" ? reviewed : apply,
    );
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([summary("take-a-hike")]);

    renderPage("/listings/deploy/apply-fast");
    await screen.findByText("Some listings became stale.");
    await clock.user.click(screen.getByRole("button", { name: "← Back to listings" }));
    await screen.findByText("listings page");
    await clock.advance(MARK_SEEN_GRACE_MS);

    expect(runsApi.markRunSeen).not.toHaveBeenCalledWith("apply-fast");
  });

  it("drops an apply run left while its reviewed plan was still loading", async () => {
    let releaseReview: (run: RunDetail) => void = () => {};
    const staleReview = new Promise<RunDetail>((resolve) => {
      releaseReview = resolve;
    });
    const apply = runDetail({
      id: "apply-1",
      kind: "apply",
      phase: "applying",
      reviewed_run_id: "plan-1",
      events: [{ type: "phase", id: 1, phase: "applying" }],
    });
    const next = runDetail({
      id: "batch-2",
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
    });
    vi.spyOn(runsApi, "getRun").mockImplementation(async (id) => {
      if (id === "apply-1") return apply;
      if (id === "plan-1") return staleReview;
      return next;
    });
    vi.spyOn(listingsApi, "listListings").mockResolvedValue([summary("take-a-hike")]);
    const opened = vi.spyOn(runStreamModule, "openRunStream").mockReturnValue({ close: vi.fn() });

    function GoToNextRun() {
      const navigate = useNavigate();
      return (
        <button type="button" onClick={() => navigate("/listings/deploy/batch-2")}>
          next run
        </button>
      );
    }
    render(
      <MemoryRouter initialEntries={["/listings/deploy/apply-1"]}>
        <GoToNextRun />
        <Routes>
          <Route path="/listings/deploy/:runId" element={<BatchDeployPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(runsApi.getRun).toHaveBeenCalledWith("plan-1"));
    await userEvent.click(screen.getByRole("button", { name: "next run" }));
    expect(await screen.findByRole("heading", { name: "Review all changes" })).toBeInTheDocument();

    releaseReview(runDetail({ id: "plan-1", phase: "ready", events: [] }));
    await staleReview;
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(screen.getByRole("heading", { name: "Review all changes" })).toBeInTheDocument();
    expect(opened).not.toHaveBeenCalledWith("apply-1", expect.anything());
  });

  function publishReview(plans: PlanDTO[]) {
    return runDetail({
      id: "plan-1",
      phase: "ready",
      listings: plans.map((p) => p.listing),
      events: [
        { type: "phase", id: 1, phase: "queued" },
        ...plans.map((p, index) => ({
          type: "listing_planned" as const,
          id: index + 2,
          listing: p.listing,
          plan: p,
          fingerprint: `fp-${p.listing}`,
        })),
        { type: "phase", id: plans.length + 2, phase: "ready" },
      ],
    });
  }

  function renderReview(plans: PlanDTO[]) {
    vi.spyOn(runsApi, "getRun").mockResolvedValue(publishReview(plans));
    vi.spyOn(listingsApi, "listListings").mockResolvedValue(plans.map((p) => summary(p.listing)));
    streamStub();
    render(
      <MemoryRouter initialEntries={["/listings/deploy/plan-1"]}>
        <Routes>
          <Route path="/listings/deploy/:runId" element={<BatchDeployPage />} />
        </Routes>
      </MemoryRouter>,
    );
  }

  it("opts in to publishing without planning again, naming what goes live", async () => {
    const create = vi
      .spyOn(runsApi, "createRun")
      .mockResolvedValue({ kind: "created", run: runDetail({ id: "apply-1", kind: "apply" }) });
    renderReview([
      plan({ listing: "alpha", is_live: false, publishable: true }),
      plan({ listing: "beta", is_live: true, publishable: false }),
    ]);

    const toggle = await screen.findByRole("checkbox", { name: /Publish new listings on Etsy/ });
    expect(toggle).not.toBeChecked();
    expect(screen.getByText(/On, 1 would go live/)).toBeInTheDocument();
    await userEvent.click(toggle);

    expect(toggle).toBeChecked();
    expect(create).not.toHaveBeenCalled();
    const live = screen.getByRole("list", { name: "Listings that go live" });
    expect(within(live).getByText("alpha")).toBeInTheDocument();
    expect(within(live).queryByText("beta")).toBeNull();

    await userEvent.click(await screen.findByRole("button", { name: /Apply 2 listings/ }));

    // The review's own fingerprints: the publish step is left out of them.
    await waitFor(() =>
      expect(create).toHaveBeenLastCalledWith({
        kind: "apply",
        scope: "workspace",
        listings: ["alpha", "beta"],
        expect: { alpha: "fp-alpha", beta: "fp-beta" },
        reviewed_run_id: "plan-1",
        publish: true,
      }),
    );
  });

  it("does not offer publishing when nothing would go live", async () => {
    renderReview([plan({ listing: "alpha", is_live: true, publishable: false })]);

    await screen.findByRole("button", { name: /Apply 1 listing/ });
    expect(screen.queryByRole("checkbox", { name: /Publish new listings on Etsy/ })).toBeNull();
  });

  it("can apply a set of drafts with nothing else to change, once publishing is on", async () => {
    renderReview([
      plan({
        listing: "alpha",
        is_live: false,
        publishable: true,
        stage_plans: [stage("render", { will_run: false })],
      }),
    ]);

    expect(await screen.findByText("Everything is up to date.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: /Publish new listings on Etsy/ }));

    expect(screen.queryByText("Everything is up to date.")).toBeNull();
    expect(screen.getByRole("button", { name: /Apply 1 listing/ })).toBeEnabled();
  });
});
