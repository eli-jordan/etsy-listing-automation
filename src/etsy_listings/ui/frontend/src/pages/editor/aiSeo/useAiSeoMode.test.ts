import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as listingsApi from "../../../api/listings";
import * as seoApi from "../../../api/seo";
import {
  aiRunSummary,
  briefEvent,
  type FakeAiRuns,
  fakeAiRuns,
  phaseEvent,
  proposalEvent,
} from "../../../test/aiRuns";
import type {
  ListingDetail,
  SeoProposalResponse,
  SeoReadinessResponse,
  WorkspaceSummary,
} from "../../../types";
import { loadStoredProposal } from "./aiSeoStorage";
import { useAiSeoMode } from "./useAiSeoMode";

function detail(over: Partial<ListingDetail> = {}): ListingDetail {
  return {
    garment_profile: "comfort-colors-1717",
    design: { default: "designs/take-a-hike.png" },
    colors: ["black"],
    brief: "A relaxed hiking tee.",
    garment_materials: ["ring-spun cotton"],
    garment_product_type: "tee",
    garment_brand: "Comfort Colors",
    garment_model: "1717",
    prices: {},
    price_overrides: {},
    artwork: {},
    pricing_plan: null,
    etsy: {
      title: "Take A Hike Tee",
      description: { lead: "", text: null, ref: null },
      tags: [],
      variation_images: null,
      renewal: null,
      section: "Graphic Tees",
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
    description_composed: "",
    design_content_hash: null,
    ...over,
  };
}

function proposal(over: Partial<SeoProposalResponse> = {}): SeoProposalResponse {
  return {
    titles: ["Title A", "Title B", "Title C"],
    tags: Array.from({ length: 20 }, (_, i) => `tag-${i}`),
    description_leads: ["Lead A", "Lead B", "Lead C"],
    rationale: [],
    warnings: [],
    observed_text: "",
    snapshot: {
      brief: "A relaxed hiking tee.",
      product_type: "tee",
      etsy_category: "Graphic Tees",
      materials: ["ring-spun cotton"],
      colors: ["black"],
      garment_brand: "Comfort Colors",
      garment_model: "1717",
      garment_profile: "comfort-colors-1717",
      design: { default: "designs/take-a-hike.png" },
      design_content_hash: null,
    },
    // Relative to now -- see `aiSeoStorage.test.ts` for why a fixed pair is a
    // fixture with an expiry date of its own.
    generated_at: new Date(Date.now() - 60_000).toISOString(),
    expires_at: new Date(Date.now() + 86_400_000).toISOString(),
    ...over,
  };
}

function mockWorkspace(shopName: string | null = "Pine & Thread", storageId = "workspace-1") {
  const workspace: WorkspaceSummary = { shop_name: shopName, storage_id: storageId };
  vi.spyOn(listingsApi, "getWorkspace").mockResolvedValue(workspace);
}

function mockReadiness(response: SeoReadinessResponse) {
  vi.spyOn(seoApi, "getSeoReadiness").mockResolvedValue(response);
}

let runs: FakeAiRuns;

beforeEach(() => {
  localStorage.clear();
  runs = fakeAiRuns();
});

function aiRunDone() {
  return aiRunSummary({ phase: "done" });
}

/** The run behind the button delivers `body` and ends. */
async function delivers(body: SeoProposalResponse) {
  await waitFor(() => expect(runs.streams).toHaveLength(1));
  runs.emit(proposalEvent(body), phaseEvent("done"));
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("useAiSeoMode availability", () => {
  it("is unavailable without calling the readiness endpoint for an unnamed draft", async () => {
    mockWorkspace();
    const readiness = vi.spyOn(seoApi, "getSeoReadiness");
    const onUpdate = vi.fn();
    const onFlush = vi.fn();

    const { result } = renderHook(() => useAiSeoMode(detail({ name: "" }), onUpdate, onFlush));

    await waitFor(() => expect(result.current.available).toBe(false));
    expect(readiness).not.toHaveBeenCalled();
  });

  it("is unavailable without calling the readiness endpoint when there is no design", async () => {
    mockWorkspace();
    const readiness = vi.spyOn(seoApi, "getSeoReadiness");

    const { result } = renderHook(() => useAiSeoMode(detail({ design: {} }), vi.fn(), vi.fn()));

    await waitFor(() => expect(result.current.available).toBe(false));
    expect(readiness).not.toHaveBeenCalled();
  });

  // Regression test for f21e864: `getWorkspace()` used to fire on every
  // mount regardless of prerequisites, sending an unmocked network call from
  // any editor test whose fixture had a design but no brief yet (most of
  // them) and flaking unrelated tests under CI parallelism. It must stay
  // gated behind the same prerequisites as the readiness call.
  it("does not call getWorkspace when prerequisites are unmet", async () => {
    const workspace = vi.spyOn(listingsApi, "getWorkspace");

    const { result } = renderHook(() => useAiSeoMode(detail({ design: {} }), vi.fn(), vi.fn()));

    await waitFor(() => expect(result.current.available).toBe(false));
    expect(workspace).not.toHaveBeenCalled();
  });

  it("is available with an empty brief, and the click drafts one", async () => {
    mockWorkspace();
    mockReadiness({ ready: true });

    const { result } = renderHook(() => useAiSeoMode(detail({ brief: "   " }), vi.fn(), vi.fn()));

    await waitFor(() => expect(result.current.available).toBe(true));
    expect(result.current.draftsBrief).toBe(true);
    expect(result.current.requirements.map((requirement) => requirement.label)).not.toContain(
      "Brief filled in",
    );

    act(() => result.current.generate());
    expect(runs.start).toHaveBeenCalledWith("take-a-hike", { draftBrief: true });
  });

  it("asks the readiness endpoint once name/design/brief are present, and reflects its answer", async () => {
    mockWorkspace();
    mockReadiness({ ready: true });

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));

    await waitFor(() => expect(result.current.available).toBe(true));
  });

  it("stays unavailable when the readiness endpoint says not ready", async () => {
    mockWorkspace();
    mockReadiness({ ready: false, reason: "no AI provider is ready" });

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));

    await waitFor(() => expect(result.current.available).toBe(false));
  });

  it("stays unavailable when the readiness check itself fails", async () => {
    mockWorkspace();
    vi.spyOn(seoApi, "getSeoReadiness").mockRejectedValue(new Error("network down"));

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));

    await waitFor(() => expect(result.current.available).toBe(false));
  });
});

describe("useAiSeoMode generation", () => {
  it("starts a run without drafting, and keeps the proposal it delivers", async () => {
    mockWorkspace();
    mockReadiness({ ready: true });
    const body = proposal();

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));
    await waitFor(() => expect(result.current.available).toBe(true));

    act(() => result.current.generate());
    expect(result.current.phase).toBe("loading");
    expect(runs.start).toHaveBeenCalledWith("take-a-hike", { draftBrief: false });

    await delivers(body);
    expect(result.current.phase).toBe("idle");
    expect(result.current.proposal?.proposal).toEqual(body);
    expect(loadStoredProposal({ workspace: "workspace-1", listing: "take-a-hike" })).not.toBeNull();
  });

  it("exposes the run, and when it started", async () => {
    mockWorkspace();
    mockReadiness({ ready: true });

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));
    await waitFor(() => expect(result.current.available).toBe(true));
    act(() => result.current.generate());

    await waitFor(() => expect(result.current.run.steps).toHaveLength(3));
    expect(result.current.startedAt).toBe(result.current.run.startedAt);
    expect(result.current.startedAt).not.toBeNull();
  });

  it("moves to a failed phase, says why, and stores nothing when the run fails", async () => {
    mockWorkspace();
    mockReadiness({ ready: true });

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));
    await waitFor(() => expect(result.current.available).toBe(true));

    act(() => result.current.generate());
    await waitFor(() => expect(runs.streams).toHaveLength(1));
    runs.emit(phaseEvent("failed", "Etsy market search failed: timed out"));

    expect(result.current.phase).toBe("failed");
    expect(result.current.failure).toBe("Etsy market search failed: timed out");
    expect(result.current.proposal).toBeNull();
  });

  it("cancels the run and returns to idle with no proposal", async () => {
    mockWorkspace();
    mockReadiness({ ready: true });

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));
    await waitFor(() => expect(result.current.available).toBe(true));

    act(() => result.current.generate());
    await waitFor(() => expect(runs.streams).toHaveLength(1));
    act(() => result.current.cancel());
    runs.emit(phaseEvent("cancelled"));

    expect(runs.cancel).toHaveBeenCalledWith("run-1");
    expect(result.current.phase).toBe("idle");
    expect(result.current.proposal).toBeNull();
  });

  it("does not reopen drawers the seller resolved when the run replays after a reload", async () => {
    mockWorkspace();
    mockReadiness({ ready: true });
    const body = proposal();
    const first = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));
    await waitFor(() => expect(first.result.current.available).toBe(true));
    act(() => first.result.current.generate());
    await delivers(body);
    act(() => first.result.current.rejectTitle());
    first.unmount();

    runs.find.mockResolvedValue(aiRunDone());
    const second = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));
    await waitFor(() => expect(runs.streams).toHaveLength(2));
    runs.emit(proposalEvent(body), phaseEvent("done"));

    await waitFor(() => expect(second.result.current.proposal).not.toBeNull());
    expect(second.result.current.proposal?.unresolved.title).toBe(false);
  });
});

describe("useAiSeoMode and the auto chain's brief", () => {
  it("puts a drafted brief into an empty field without saving it again", async () => {
    mockWorkspace();
    mockReadiness({ ready: true });
    const onUpdate = vi.fn();
    const onAdopt = vi.fn();
    const { result } = renderHook(() =>
      useAiSeoMode(detail({ brief: "" }), onUpdate, vi.fn(), undefined, onAdopt),
    );

    act(() => result.current.run.start({ draftBrief: true }));
    await waitFor(() => expect(runs.streams).toHaveLength(1));
    runs.emit(briefEvent("Retro sunset over mountains."));

    expect(onAdopt).toHaveBeenCalledWith({ brief: "Retro sunset over mountains." });
    expect(onUpdate).not.toHaveBeenCalled();
  });

  it("leaves a brief the seller typed meanwhile alone", async () => {
    mockWorkspace();
    mockReadiness({ ready: true });
    const onAdopt = vi.fn();
    const { result, rerender } = renderHook(
      (d: ListingDetail) => useAiSeoMode(d, vi.fn(), vi.fn(), undefined, onAdopt),
      { initialProps: detail({ brief: "" }) },
    );
    act(() => result.current.run.start({ draftBrief: true }));
    await waitFor(() => expect(runs.streams).toHaveLength(1));

    rerender(detail({ brief: "My own words." }));
    runs.emit(briefEvent("Retro sunset over mountains."));

    expect(onAdopt).not.toHaveBeenCalled();
  });

  it("keeps a proposal that arrives before the workspace id does", async () => {
    let resolveWorkspace: (workspace: WorkspaceSummary) => void = () => {};
    vi.spyOn(listingsApi, "getWorkspace").mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveWorkspace = resolve;
        }),
    );
    mockReadiness({ ready: true });
    const body = proposal();
    const { result } = renderHook(() => useAiSeoMode(detail({ brief: "" }), vi.fn(), vi.fn()));
    act(() => result.current.run.start({ draftBrief: true }));
    await waitFor(() => expect(runs.streams).toHaveLength(1));
    runs.emit(proposalEvent(body), phaseEvent("done"));
    expect(result.current.proposal).toBeNull();

    await act(async () => {
      resolveWorkspace({ shop_name: "Pine & Thread", storage_id: "workspace-1" });
    });

    await waitFor(() => expect(result.current.proposal?.proposal).toEqual(body));
  });
});

async function readyHookWithProposal(onUpdate = vi.fn(), onFlush = vi.fn()) {
  mockWorkspace();
  mockReadiness({ ready: true });
  const body = proposal();

  const { result, rerender } = renderHook(
    (d: ListingDetail) => useAiSeoMode(d, onUpdate, onFlush),
    { initialProps: detail() },
  );
  await waitFor(() => expect(result.current.available).toBe(true));
  act(() => result.current.generate());
  await delivers(body);
  await waitFor(() => expect(result.current.proposal).not.toBeNull());
  return { result, rerender, body };
}

describe("useAiSeoMode acceptance", () => {
  it("choosing a title updates the field, flushes, and resolves only the title drawer", async () => {
    const onUpdate = vi.fn();
    const onFlush = vi.fn();
    const { result } = await readyHookWithProposal(onUpdate, onFlush);

    act(() => result.current.chooseTitle("Title B"));

    expect(onUpdate).toHaveBeenCalledWith({ etsy: { title: "Title B" } });
    expect(onFlush).toHaveBeenCalled();
    expect(result.current.proposal?.unresolved).toEqual({ title: false, tags: true, lead: true });
  });

  it("rejecting the title drawer closes it without touching the field", async () => {
    const onUpdate = vi.fn();
    const { result } = await readyHookWithProposal(onUpdate);

    act(() => result.current.rejectTitle());

    expect(onUpdate).not.toHaveBeenCalled();
    expect(result.current.proposal?.unresolved.title).toBe(false);
  });

  it("choosing a lead patches the structured description and resolves only the lead drawer", async () => {
    const onUpdate = vi.fn();
    const { result } = await readyHookWithProposal(onUpdate);

    act(() => result.current.chooseLead("Lead B"));

    expect(onUpdate).toHaveBeenCalledWith({
      etsy: { description: { lead: "Lead B", text: null, ref: null } },
    });
    expect(result.current.proposal?.unresolved).toEqual({ title: true, tags: true, lead: false });
  });

  it("toggling an unselected tag adds it without closing the tags drawer", async () => {
    const onUpdate = vi.fn();
    const { result } = await readyHookWithProposal(onUpdate);

    act(() => result.current.toggleTag("tag-0"));

    expect(onUpdate).toHaveBeenCalledWith({ etsy: { tags: ["tag-0"] } });
    expect(result.current.proposal?.unresolved.tags).toBe(true);
  });

  it("toggling a selected tag removes it again", async () => {
    const onUpdate = vi.fn();
    mockWorkspace();
    mockReadiness({ ready: true });
    const body = proposal();

    const { result } = renderHook((d: ListingDetail) => useAiSeoMode(d, onUpdate, vi.fn()), {
      initialProps: detail({ etsy: { ...detail().etsy, tags: ["tag-0"] } }),
    });
    await waitFor(() => expect(result.current.available).toBe(true));
    act(() => result.current.generate());
    await delivers(body);

    act(() => result.current.toggleTag("tag-0"));

    expect(onUpdate).toHaveBeenCalledWith({ etsy: { tags: [] } });
  });

  it("does not add a 14th tag", async () => {
    const onUpdate = vi.fn();
    mockWorkspace();
    mockReadiness({ ready: true });
    const body = proposal();
    const thirteen = Array.from({ length: 13 }, (_, i) => `existing-${i}`);

    const { result } = renderHook(() =>
      useAiSeoMode(detail({ etsy: { ...detail().etsy, tags: thirteen } }), onUpdate, vi.fn()),
    );
    await waitFor(() => expect(result.current.available).toBe(true));
    act(() => result.current.generate());
    await delivers(body);

    act(() => result.current.toggleTag("tag-0"));

    expect(onUpdate).not.toHaveBeenCalled();
  });

  it("accepting best 13 replaces the whole tag collection and closes the tags drawer", async () => {
    const onUpdate = vi.fn();
    const { result, body } = await readyHookWithProposal(onUpdate);

    act(() => result.current.acceptBestTags());

    expect(onUpdate).toHaveBeenCalledWith({ etsy: { tags: body.tags.slice(0, 13) } });
    expect(result.current.proposal?.unresolved.tags).toBe(false);
  });

  it("closing the tags drawer keeps already-selected tags and resolves only tags", async () => {
    const onUpdate = vi.fn();
    const { result } = await readyHookWithProposal(onUpdate);

    act(() => result.current.toggleTag("tag-0"));
    act(() => result.current.closeTags());

    expect(result.current.proposal?.unresolved).toEqual({ title: true, tags: false, lead: true });
  });

  it("removes the stored proposal entirely once every drawer resolves", async () => {
    const { result } = await readyHookWithProposal();

    act(() => result.current.rejectTitle());
    act(() => result.current.closeTags());
    act(() => result.current.rejectLead());

    expect(result.current.proposal).toBeNull();
    expect(loadStoredProposal({ workspace: "workspace-1", listing: "take-a-hike" })).toBeNull();
  });
});

describe("useAiSeoMode stale state", () => {
  it("keeps an in-flight proposal tied to the saved inputs it used", async () => {
    mockWorkspace();
    mockReadiness({ ready: true });
    const { result, rerender } = renderHook(
      (d: ListingDetail) => useAiSeoMode(d, vi.fn(), vi.fn()),
      {
        initialProps: detail(),
      },
    );
    await waitFor(() => expect(result.current.available).toBe(true));

    act(() => result.current.generate());
    await waitFor(() => expect(runs.streams).toHaveLength(1));
    rerender(detail({ design: { default: "designs/new.png" }, garment_profile: "new-profile" }));
    runs.emit(proposalEvent(proposal()), phaseEvent("done"));

    expect(result.current.stale).toBe(true);
  });

  it("marks the proposal stale once the brief changes, and refuses further acceptance", async () => {
    const onUpdate = vi.fn();
    const { result, rerender } = await readyHookWithProposal(onUpdate);
    expect(result.current.stale).toBe(false);

    rerender(detail({ brief: "A totally different brief." }));

    expect(result.current.stale).toBe(true);

    act(() => result.current.chooseTitle("Title B"));
    expect(onUpdate).not.toHaveBeenCalled();
    act(() => result.current.toggleTag("tag-0"));
    expect(onUpdate).not.toHaveBeenCalled();
    act(() => result.current.acceptBestTags());
    expect(onUpdate).not.toHaveBeenCalled();
  });
});

describe("useAiSeoMode restoring from storage", () => {
  it("restores an unresolved proposal already in local storage on mount", async () => {
    mockWorkspace();
    mockReadiness({ ready: true });
    const body = proposal();
    const { toStoredProposal, saveStoredProposal } = await import("./aiSeoStorage");
    saveStoredProposal(
      { workspace: "workspace-1", listing: "take-a-hike" },
      toStoredProposal(body),
    );

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));

    await waitFor(() => expect(result.current.proposal?.proposal).toEqual(body));
  });

  it("does not restore an expired proposal", async () => {
    mockWorkspace();
    mockReadiness({ ready: true });
    const body = proposal({ expires_at: "2020-01-01T00:00:00Z" });
    const { toStoredProposal, saveStoredProposal } = await import("./aiSeoStorage");
    saveStoredProposal(
      { workspace: "workspace-1", listing: "take-a-hike" },
      toStoredProposal(body),
    );

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));
    await waitFor(() => expect(result.current.available).toBe(true));

    expect(result.current.proposal).toBeNull();
  });
});
