import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
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
    expect(screen.getByRole("button", { name: /Apply 1 listing/ })).toBeDisabled();
    expect(streams).toHaveLength(0);
    await waitFor(() => expect(runsApi.markRunSeen).toHaveBeenCalledWith("batch-1"));
  });

  it("does not treat an individual or apply run as a workspace review", async () => {
    vi.spyOn(runsApi, "getRun").mockResolvedValue(
      runDetail({
        kind: "apply",
        scope: "workspace",
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
});
