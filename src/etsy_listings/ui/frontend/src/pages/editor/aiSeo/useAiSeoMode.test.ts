import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as seoApi from "../../../api/seo";
import {
  aiRunSummary,
  briefEvent,
  type FakeAiRuns,
  fakeAiRuns,
  listingProposal,
  phaseEvent,
  proposalEvent,
} from "../../../test/aiRuns";
import type { ListingDetail, ListingProposal, SeoReadinessResponse } from "../../../types";
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

const proposal = listingProposal;

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
async function delivers(body: ListingProposal) {
  await waitFor(() => expect(runs.streams).toHaveLength(1));
  runs.emit(proposalEvent(body), phaseEvent("done"));
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("useAiSeoMode availability", () => {
  it("is unavailable without calling the readiness endpoint for an unnamed draft", async () => {
    const readiness = vi.spyOn(seoApi, "getSeoReadiness");
    const onUpdate = vi.fn();
    const onFlush = vi.fn();

    const { result } = renderHook(() => useAiSeoMode(detail({ name: "" }), onUpdate, onFlush));

    await waitFor(() => expect(result.current.available).toBe(false));
    expect(readiness).not.toHaveBeenCalled();
  });

  it("is unavailable without calling the readiness endpoint when there is no design", async () => {
    const readiness = vi.spyOn(seoApi, "getSeoReadiness");

    const { result } = renderHook(() => useAiSeoMode(detail({ design: {} }), vi.fn(), vi.fn()));

    await waitFor(() => expect(result.current.available).toBe(false));
    expect(readiness).not.toHaveBeenCalled();
  });

  it("is available with an empty brief, and the click drafts one", async () => {
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
    mockReadiness({ ready: true });

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));

    await waitFor(() => expect(result.current.available).toBe(true));
  });

  it("stays unavailable when the readiness endpoint says not ready", async () => {
    mockReadiness({ ready: false, reason: "no AI provider is ready" });

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));

    await waitFor(() => expect(result.current.available).toBe(false));
  });

  it("stays unavailable when the readiness check itself fails", async () => {
    vi.spyOn(seoApi, "getSeoReadiness").mockRejectedValue(new Error("network down"));

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));

    await waitFor(() => expect(result.current.available).toBe(false));
  });
});

describe("useAiSeoMode generation", () => {
  it("starts a run without drafting, and keeps the proposal it delivers", async () => {
    mockReadiness({ ready: true });
    const body = proposal();

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));
    await waitFor(() => expect(result.current.available).toBe(true));

    act(() => result.current.generate());
    expect(result.current.phase).toBe("loading");
    expect(runs.start).toHaveBeenCalledWith("take-a-hike", { draftBrief: false });

    await delivers(body);
    expect(result.current.phase).toBe("idle");
    expect(result.current.proposal).toEqual(body);
  });

  it("exposes the run, and when it started", async () => {
    mockReadiness({ ready: true });

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));
    await waitFor(() => expect(result.current.available).toBe(true));
    act(() => result.current.generate());

    await waitFor(() => expect(result.current.run.steps).toHaveLength(3));
    expect(result.current.startedAt).toBe(result.current.run.startedAt);
    expect(result.current.startedAt).not.toBeNull();
  });

  it("moves to a failed phase, says why, and stores nothing when the run fails", async () => {
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
    mockReadiness({ ready: true });
    const body = proposal();
    const first = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));
    await waitFor(() => expect(first.result.current.available).toBe(true));
    act(() => first.result.current.generate());
    await delivers(body);
    act(() => first.result.current.rejectTitle());
    await waitFor(() => expect(runs.cached.proposal?.resolution.title).toBe("dismissed"));
    first.unmount();

    runs.find.mockResolvedValue(aiRunDone());
    const second = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));
    await waitFor(() => expect(second.result.current.proposal).not.toBeNull());
    await waitFor(() => expect(runs.streams).toHaveLength(2));
    const cached = runs.cached.proposal;
    runs.emit(proposalEvent(body), phaseEvent("done"));
    runs.cached.proposal = cached;

    expect(second.result.current.proposal?.resolution.title).toBe("dismissed");
  });
});

describe("useAiSeoMode and the auto chain's brief", () => {
  it("puts a drafted brief into an empty field without saving it again", async () => {
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
});

/** What the server has recorded for each section, once the PATCH lands, and
 * what the hook shows meanwhile -- both, because a resolution is shown at
 * once and kept by the server. */
async function resolved(
  result: { current: ReturnType<typeof useAiSeoMode> },
  expected: ListingProposal["resolution"],
) {
  const pending = Object.values(expected).includes("pending");
  expect(result.current.proposal?.resolution ?? null).toEqual(pending ? expected : null);
  await waitFor(() => expect(runs.cached.proposal?.resolution).toEqual(expected));
}

async function readyHookWithProposal(onUpdate = vi.fn(), onFlush = vi.fn()) {
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
    await resolved(result, { title: "accepted", tags: "pending", lead: "pending" });
  });

  it("rejecting the title drawer closes it without touching the field", async () => {
    const onUpdate = vi.fn();
    const { result } = await readyHookWithProposal(onUpdate);

    act(() => result.current.rejectTitle());

    expect(onUpdate).not.toHaveBeenCalled();
    await resolved(result, { title: "dismissed", tags: "pending", lead: "pending" });
  });

  it("choosing a lead patches the structured description and resolves only the lead drawer", async () => {
    const onUpdate = vi.fn();
    const { result } = await readyHookWithProposal(onUpdate);

    act(() => result.current.chooseLead("Lead B"));

    expect(onUpdate).toHaveBeenCalledWith({
      etsy: { description: { lead: "Lead B", text: null, ref: null } },
    });
    await resolved(result, { title: "pending", tags: "pending", lead: "accepted" });
  });

  it("toggling an unselected tag adds it without closing the tags drawer", async () => {
    const onUpdate = vi.fn();
    const { result } = await readyHookWithProposal(onUpdate);

    act(() => result.current.toggleTag("tag-0"));

    expect(onUpdate).toHaveBeenCalledWith({ etsy: { tags: ["tag-0"] } });
    expect(result.current.proposal?.resolution.tags).toBe("pending");
  });

  it("toggling a selected tag removes it again", async () => {
    const onUpdate = vi.fn();
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

    expect(onUpdate).toHaveBeenCalledWith({ etsy: { tags: body.proposal.tags.slice(0, 13) } });
    await resolved(result, { title: "pending", tags: "accepted", lead: "pending" });
  });

  it("closing the tags drawer keeps already-selected tags and resolves only tags", async () => {
    const onUpdate = vi.fn();
    const { result } = await readyHookWithProposal(onUpdate);

    act(() => result.current.toggleTag("tag-0"));
    act(() => result.current.closeTags());

    await resolved(result, { title: "pending", tags: "dismissed", lead: "pending" });
  });

  it("has nothing pending once every drawer resolves, and the server keeps the record", async () => {
    const { result } = await readyHookWithProposal();

    act(() => result.current.rejectTitle());
    act(() => result.current.closeTags());
    act(() => result.current.rejectLead());

    expect(result.current.proposal).toBeNull();
    await waitFor(() =>
      expect(runs.cached.proposal?.resolution).toEqual({
        title: "dismissed",
        tags: "dismissed",
        lead: "dismissed",
      }),
    );
    expect(result.current.proposal).toBeNull();
  });

  it("records each resolution on the proposal it was made on", async () => {
    const { result, body } = await readyHookWithProposal();

    act(() => result.current.chooseTitle("Title B"));

    expect(runs.resolveProposal).toHaveBeenCalledWith("take-a-hike", {
      generated_at: body.generated_at,
      title: "accepted",
    });
  });

  it("reads the current proposal again when the one it resolved was replaced", async () => {
    const { result } = await readyHookWithProposal();
    const fresh = proposal({ generated_at: "2026-09-24T00:00:00Z" });
    runs.cached.proposal = fresh;

    act(() => result.current.rejectTitle());

    await waitFor(() => expect(result.current.proposal).toEqual(fresh));
  });
});

describe("useAiSeoMode stale state", () => {
  it("names what changed, from the server, and keeps every choice usable", async () => {
    mockReadiness({ ready: true });
    runs.cached.proposal = proposal({
      stale: { is_stale: true, reasons: ["brief edited since", "colours changed since"] },
    });
    const onUpdate = vi.fn();

    const { result } = renderHook(() => useAiSeoMode(detail(), onUpdate, vi.fn()));
    await waitFor(() => expect(result.current.proposal).not.toBeNull());

    expect(result.current.staleReason).toBe("brief edited since, colours changed since");
    act(() => result.current.chooseTitle("Title B"));
    act(() => result.current.toggleTag("tag-0"));
    act(() => result.current.acceptBestTags());
    expect(onUpdate).toHaveBeenCalledWith({ etsy: { title: "Title B" } });
    expect(onUpdate).toHaveBeenCalledWith({ etsy: { tags: ["tag-0"] } });
    expect(onUpdate).toHaveBeenCalledTimes(3);
  });

  it("asks again once the listing is saved, so an edit shows up as stale", async () => {
    const { result, rerender } = await readyHookWithProposal();
    expect(result.current.staleReason).toBeNull();

    runs.cached.proposal = proposal({ stale: { is_stale: true, reasons: ["brief edited since"] } });
    rerender(detail({ brief: "A different brief.", modified_at: "2026-09-17T10:05:00Z" }));

    await waitFor(() => expect(result.current.staleReason).toBe("brief edited since"));
  });
});

describe("useAiSeoMode restoring from the server", () => {
  it("opens the listing's cached proposal on mount", async () => {
    mockReadiness({ ready: true });
    const body = proposal();
    runs.cached.proposal = body;

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));

    await waitFor(() => expect(result.current.proposal).toEqual(body));
    expect(runs.loadProposal).toHaveBeenCalledWith("take-a-hike");
  });

  it("keeps a resolved section closed", async () => {
    mockReadiness({ ready: true });
    runs.cached.proposal = proposal({
      resolution: { title: "accepted", tags: "pending", lead: "dismissed" },
    });

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));

    await waitFor(() => expect(result.current.proposal?.resolution.title).toBe("accepted"));
    expect(result.current.proposal?.resolution.lead).toBe("dismissed");
  });

  it("has nothing pending when every section of the cached proposal is resolved", async () => {
    mockReadiness({ ready: true });
    runs.cached.proposal = proposal({
      resolution: { title: "accepted", tags: "accepted", lead: "dismissed" },
    });

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));

    await waitFor(() => expect(runs.loadProposal).toHaveBeenCalled());
    expect(result.current.proposal).toBeNull();
  });

  it("does not ask for a proposal an unnamed draft cannot have", async () => {
    const { result } = renderHook(() => useAiSeoMode(detail({ name: "" }), vi.fn(), vi.fn()));

    await waitFor(() => expect(result.current.available).toBe(false));
    expect(runs.loadProposal).not.toHaveBeenCalled();
  });

  it("drops the previous listing's proposal when the editor moves to another", async () => {
    mockReadiness({ ready: true });
    runs.cached.proposal = proposal();
    const { result, rerender } = renderHook(
      (d: ListingDetail) => useAiSeoMode(d, vi.fn(), vi.fn()),
      { initialProps: detail() },
    );
    await waitFor(() => expect(result.current.proposal).not.toBeNull());
    runs.cached.proposal = null;

    rerender(detail({ name: "another-listing" }));

    expect(result.current.proposal).toBeNull();
    await waitFor(() => expect(runs.loadProposal).toHaveBeenCalledWith("another-listing"));
    expect(result.current.proposal).toBeNull();
  });
});
