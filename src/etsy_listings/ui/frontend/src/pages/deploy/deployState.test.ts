import { describe, expect, it } from "vitest";
import { deployState, initialDeployState } from "./deployState";
import type { PlanDTO, RunEvent, RunPhase, StagePlanDTO } from "../../types";

/**
 * `RunEvent[] -> phase, per-stage runtime, plan, previews` (docs/deploy-changes.md,
 * frontend module table). One recorded sequence per scenario the Testing
 * table names: plan, blocked, nothing to do, stale, failed mid-apply,
 * reattach mid-apply.
 *
 * Event shapes are exactly what `ui/runs/events.py`'s DTOs serialise --
 * `type`/`id` discriminated, stage plans nested verbatim -- so a fixture here
 * is what `GET /api/runs/{id}` would actually hand back, not an invented
 * shorthand.
 */

let nextId = 1;
function reset() {
  nextId = 1;
}
function id(): number {
  return nextId++;
}

function stagePlan(
  overrides: Partial<StagePlanDTO> & { stage: StagePlanDTO["stage"] },
): StagePlanDTO {
  return {
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

function plan(stagePlans: StagePlanDTO[], overrides: Partial<PlanDTO> = {}): PlanDTO {
  return {
    listing: "mushroom-club-tee",
    is_live: false,
    etsy_listing_id: 1698234512,
    stage_plans: stagePlans,
    ...overrides,
  };
}

const RENDER_RUN = stagePlan({
  stage: "render",
  will_run: true,
  reason: "referenced scenes changed",
  snapshot: {
    scenes: [
      {
        scene: "lifestyle-02:moss",
        template: "lifestyle-02",
        colour: "moss",
        state: "missing",
        preview: false,
      },
    ],
  },
});
const PRODUCT_RUN = stagePlan({
  stage: "printify_product",
  will_run: true,
  reason: "the product differs from the listing",
});
const PUBLISH_SKIP = stagePlan({ stage: "publish", will_run: false });
const ETSY_LISTING_RUN = stagePlan({
  stage: "etsy_listing",
  will_run: true,
  reason: "the listing's copy or settings changed",
});
const ETSY_MEDIA_RUN = stagePlan({
  stage: "etsy_media",
  will_run: true,
  reason: "the media manifest changed",
});

function checking(stage: string, listing = "mushroom-club-tee"): RunEvent {
  return { type: "stage_checking", id: id(), listing, stage };
}
function planned(stagePlanValue: StagePlanDTO, listing = "mushroom-club-tee"): RunEvent {
  return { type: "stage_planned", id: id(), listing, stage_plan: stagePlanValue };
}
function listingPlanned(
  planValue: PlanDTO,
  fingerprint: string,
  listing = "mushroom-club-tee",
): RunEvent {
  return { type: "listing_planned", id: id(), listing, plan: planValue, fingerprint };
}
function phase(p: RunPhase): RunEvent {
  return { type: "phase", id: id(), phase: p };
}

describe("deployState: a plan with changes", () => {
  it("walks queued -> planning -> planned -> previewing -> ready, filling stages and previews", () => {
    reset();
    const fullPlan = plan([
      RENDER_RUN,
      PRODUCT_RUN,
      PUBLISH_SKIP,
      ETSY_LISTING_RUN,
      ETSY_MEDIA_RUN,
    ]);
    const events: RunEvent[] = [
      phase("queued"),
      phase("planning"),
      checking("render"),
      planned(RENDER_RUN),
      checking("printify_product"),
      planned(PRODUCT_RUN),
      checking("publish"),
      planned(PUBLISH_SKIP),
      checking("etsy_listing"),
      planned(ETSY_LISTING_RUN),
      checking("etsy_media"),
      planned(ETSY_MEDIA_RUN),
      listingPlanned(fullPlan, "fp-1"),
      phase("planned"),
      phase("previewing"),
      {
        type: "preview_rendered",
        id: id(),
        listing: "mushroom-club-tee",
        template: "lifestyle-02",
        colour: "moss",
      },
      phase("ready"),
    ];

    const state = deployState(events);

    expect(state.phase).toBe("ready");
    expect(state.plan).toEqual(fullPlan);
    expect(state.fingerprint).toBe("fp-1");
    expect(state.stale).toBe(false);
    expect(state.failureMessage).toBeNull();
    expect(state.previewsRendered.has("lifestyle-02|moss")).toBe(true);
  });

  it("shows the stage currently being checked before its own stage_planned arrives", () => {
    reset();
    const events: RunEvent[] = [phase("queued"), phase("planning"), checking("render")];

    const state = deployState(events);

    expect(state.checkingStage).toBe("render");
    expect(state.plan).toBeNull();
  });
});

describe("deployState: blocked", () => {
  it("carries the blocked stage's message through the resolved plan", () => {
    reset();
    const blockedPublish = stagePlan({
      stage: "publish",
      will_run: false,
      blocked:
        "XXXL at 159 NOK is below Printify's cost of $17.20, so the product can't be updated.\n" +
        "Go back, raise the XXXL price on Listing Details, and deploy again.",
    });
    const fullPlan = plan([
      RENDER_RUN,
      PRODUCT_RUN,
      blockedPublish,
      ETSY_LISTING_RUN,
      ETSY_MEDIA_RUN,
    ]);
    const events: RunEvent[] = [
      phase("queued"),
      phase("planning"),
      planned(RENDER_RUN),
      planned(PRODUCT_RUN),
      planned(blockedPublish),
      planned(ETSY_LISTING_RUN),
      planned(ETSY_MEDIA_RUN),
      listingPlanned(fullPlan, "fp-2"),
      phase("planned"),
      phase("ready"),
    ];

    const state = deployState(events);

    expect(state.phase).toBe("ready");
    const publishPlan = state.plan?.stage_plans.find((s) => s.stage === "publish");
    expect(publishPlan?.blocked).toContain("below Printify's cost");
  });
});

describe("deployState: nothing to do", () => {
  it("resolves ready with every stage reporting no changes", () => {
    reset();
    const skipAll = [
      stagePlan({ stage: "render", will_run: false }),
      stagePlan({ stage: "printify_product", will_run: false }),
      stagePlan({ stage: "publish", will_run: false }),
      stagePlan({ stage: "etsy_listing", will_run: false }),
      stagePlan({ stage: "etsy_media", will_run: false }),
    ];
    const fullPlan = plan(skipAll);
    const events: RunEvent[] = [
      phase("queued"),
      phase("planning"),
      ...skipAll.map((s) => planned(s)),
      listingPlanned(fullPlan, "fp-3"),
      phase("planned"),
      phase("ready"),
    ];

    const state = deployState(events);

    expect(state.phase).toBe("ready");
    expect(state.plan?.stage_plans.every((s) => !s.will_run)).toBe(true);
    expect(state.previewsRendered.size).toBe(0);
  });
});

describe("deployState: an apply run that ends stale", () => {
  it("carries the fresh plan and marks the outcome stale", () => {
    reset();
    const reviewed = plan([
      RENDER_RUN,
      PRODUCT_RUN,
      PUBLISH_SKIP,
      ETSY_LISTING_RUN,
      ETSY_MEDIA_RUN,
    ]);
    const fresh = plan([
      stagePlan({ stage: "render", will_run: false }),
      PRODUCT_RUN,
      PUBLISH_SKIP,
      ETSY_LISTING_RUN,
      ETSY_MEDIA_RUN,
    ]);
    const events: RunEvent[] = [
      phase("queued"),
      phase("applying"),
      ...reviewed.stage_plans.map((s) => planned(s)),
      listingPlanned(reviewed, "fp-old"),
      {
        type: "listing_failed",
        id: id(),
        listing: "mushroom-club-tee",
        message:
          "mushroom-club-tee changed since it was planned. Plan again to review the current version.",
        stale_plan: fresh,
      },
      phase("stale"),
    ];

    const state = deployState(events);

    expect(state.phase).toBe("stale");
    expect(state.stale).toBe(true);
    expect(state.plan).toEqual(fresh);
    expect(state.failureMessage).toContain("Plan again to review");
  });
});

describe("deployState: a stage fails mid-apply", () => {
  it("marks the failed stage, leaves earlier stages applied, and ends failed", () => {
    reset();
    const fullPlan = plan([
      RENDER_RUN,
      PRODUCT_RUN,
      PUBLISH_SKIP,
      ETSY_LISTING_RUN,
      ETSY_MEDIA_RUN,
    ]);
    const events: RunEvent[] = [
      phase("queued"),
      phase("applying"),
      ...fullPlan.stage_plans.map((s) => planned(s)),
      listingPlanned(fullPlan, "fp-4"),
      { type: "stage_applying", id: id(), listing: "mushroom-club-tee", stage: "render" },
      {
        type: "progress",
        id: id(),
        listing: "mushroom-club-tee",
        stage: "render",
        message: "rendering 1 scene",
        swatches: [],
      },
      { type: "stage_applied", id: id(), listing: "mushroom-club-tee", stage: "render" },
      { type: "stage_applying", id: id(), listing: "mushroom-club-tee", stage: "printify_product" },
      {
        type: "stage_failed",
        id: id(),
        listing: "mushroom-club-tee",
        stage: "printify_product",
        message: "Printify rejected the request",
      },
      {
        type: "listing_failed",
        id: id(),
        listing: "mushroom-club-tee",
        message: "Printify rejected the request",
      },
      phase("failed"),
    ];

    const state = deployState(events);

    expect(state.phase).toBe("failed");
    expect(state.stageRuntime.render).toMatchObject({ kind: "applied" });
    expect(state.stageRuntime.printify_product).toMatchObject({
      kind: "failed",
      message: "Printify rejected the request",
    });
    expect(state.stageRuntime.etsy_listing).toBeUndefined();
    expect(state.failureMessage).toBe("Printify rejected the request");
  });
});

describe("deployState: reattaching mid-apply", () => {
  it("replays a partial event history and lands on the same state a live stream would", () => {
    reset();
    const fullPlan = plan([
      RENDER_RUN,
      PRODUCT_RUN,
      PUBLISH_SKIP,
      ETSY_LISTING_RUN,
      ETSY_MEDIA_RUN,
    ]);
    const events: RunEvent[] = [
      phase("queued"),
      phase("applying"),
      ...fullPlan.stage_plans.map((s) => planned(s)),
      listingPlanned(fullPlan, "fp-5"),
      { type: "stage_applying", id: id(), listing: "mushroom-club-tee", stage: "render" },
      {
        type: "progress",
        id: id(),
        listing: "mushroom-club-tee",
        stage: "render",
        message: "rendering 1 scene",
        swatches: [],
      },
    ];

    const state = deployState(events);

    expect(state.phase).toBe("applying");
    expect(state.stageRuntime.render).toMatchObject({
      kind: "applying",
      log: "rendering 1 scene",
    });
  });

  it("uses event timestamps so a reattached stage keeps its real elapsed time", () => {
    reset();
    const state = deployState([
      {
        type: "stage_applying",
        id: id(),
        listing: "mushroom-club-tee",
        stage: "publish",
        occurred_at: "2026-09-17T10:00:00Z",
      },
      {
        type: "stage_applied",
        id: id(),
        listing: "mushroom-club-tee",
        stage: "publish",
        occurred_at: "2026-09-17T10:00:12.500Z",
      },
    ]);

    expect(state.stageRuntime.publish).toEqual({
      kind: "applied",
      startedAt: Date.parse("2026-09-17T10:00:00Z"),
      finishedAt: Date.parse("2026-09-17T10:00:12.500Z"),
    });
  });
});

describe("initialDeployState", () => {
  it("starts queued with nothing known yet", () => {
    expect(initialDeployState.phase).toBe("queued");
    expect(initialDeployState.plan).toBeNull();
    expect(initialDeployState.stageRuntime).toEqual({});
    expect(initialDeployState.previewsRendered.size).toBe(0);
  });
});
