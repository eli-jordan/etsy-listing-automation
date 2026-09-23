import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as listingsApi from "../../../api/listings";
import * as seoApi from "../../../api/seo";
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
    },
    generated_at: "2026-09-23T00:00:00Z",
    expires_at: "2026-09-24T00:00:00Z",
    ...over,
  };
}

function mockWorkspace(shopName: string | null = "Pine & Thread") {
  const workspace: WorkspaceSummary = { shop_name: shopName };
  vi.spyOn(listingsApi, "getWorkspace").mockResolvedValue(workspace);
}

function mockReadiness(response: SeoReadinessResponse) {
  vi.spyOn(seoApi, "getSeoReadiness").mockResolvedValue(response);
}

beforeEach(() => {
  localStorage.clear();
});

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

  it("is unavailable without calling the readiness endpoint when the brief is empty", async () => {
    mockWorkspace();
    const readiness = vi.spyOn(seoApi, "getSeoReadiness");

    const { result } = renderHook(() => useAiSeoMode(detail({ brief: "   " }), vi.fn(), vi.fn()));

    await waitFor(() => expect(result.current.available).toBe(false));
    expect(readiness).not.toHaveBeenCalled();
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
  it("moves through loading to an idle phase with the stored proposal on success", async () => {
    mockWorkspace();
    mockReadiness({ ready: true });
    const body = proposal();
    vi.spyOn(seoApi, "requestSeoProposal").mockResolvedValue({ kind: "success", proposal: body });

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));
    await waitFor(() => expect(result.current.available).toBe(true));

    act(() => result.current.generate());
    expect(result.current.phase).toBe("loading");

    await waitFor(() => expect(result.current.phase).toBe("idle"));
    expect(result.current.proposal?.proposal).toEqual(body);
    expect(
      loadStoredProposal({ workspace: "Pine & Thread", listing: "take-a-hike" }),
    ).not.toBeNull();
  });

  it("moves to a failed phase and stores nothing when generation fails", async () => {
    mockWorkspace();
    mockReadiness({ ready: true });
    vi.spyOn(seoApi, "requestSeoProposal").mockResolvedValue({ kind: "failed" });

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));
    await waitFor(() => expect(result.current.available).toBe(true));

    act(() => result.current.generate());
    await waitFor(() => expect(result.current.phase).toBe("failed"));
    expect(result.current.proposal).toBeNull();
  });

  it("returns to idle with no stored proposal when generation is cancelled", async () => {
    mockWorkspace();
    mockReadiness({ ready: true });
    vi.spyOn(seoApi, "requestSeoProposal").mockResolvedValue({ kind: "cancelled" });

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));
    await waitFor(() => expect(result.current.available).toBe(true));

    act(() => result.current.generate());
    await waitFor(() => expect(result.current.phase).toBe("idle"));
    expect(result.current.proposal).toBeNull();
  });

  it("aborts the in-flight request and returns to idle when cancel() is called", async () => {
    mockWorkspace();
    mockReadiness({ ready: true });
    const requestSeoProposal = vi
      .spyOn(seoApi, "requestSeoProposal")
      .mockImplementation(() => new Promise<seoApi.SeoProposalOutcome>(() => {}));

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));
    await waitFor(() => expect(result.current.available).toBe(true));

    act(() => result.current.generate());
    expect(result.current.phase).toBe("loading");

    act(() => result.current.cancel());
    expect(result.current.phase).toBe("idle");
    const signal = requestSeoProposal.mock.calls[0]?.[1];
    expect(signal?.aborted).toBe(true);
  });

  it("aborts the in-flight request on unmount", async () => {
    mockWorkspace();
    mockReadiness({ ready: true });
    const requestSeoProposal = vi
      .spyOn(seoApi, "requestSeoProposal")
      .mockImplementation(() => new Promise<seoApi.SeoProposalOutcome>(() => {}));

    const { result, unmount } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));
    await waitFor(() => expect(result.current.available).toBe(true));

    act(() => result.current.generate());
    unmount();

    const signal = requestSeoProposal.mock.calls[0]?.[1];
    expect(signal?.aborted).toBe(true);
  });
});

async function readyHookWithProposal(onUpdate = vi.fn(), onFlush = vi.fn()) {
  mockWorkspace();
  mockReadiness({ ready: true });
  const body = proposal();
  vi.spyOn(seoApi, "requestSeoProposal").mockResolvedValue({ kind: "success", proposal: body });

  const { result, rerender } = renderHook(
    (d: ListingDetail) => useAiSeoMode(d, onUpdate, onFlush),
    { initialProps: detail() },
  );
  await waitFor(() => expect(result.current.available).toBe(true));
  act(() => result.current.generate());
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
    vi.spyOn(seoApi, "requestSeoProposal").mockResolvedValue({ kind: "success", proposal: body });

    const { result } = renderHook((d: ListingDetail) => useAiSeoMode(d, onUpdate, vi.fn()), {
      initialProps: detail({ etsy: { ...detail().etsy, tags: ["tag-0"] } }),
    });
    await waitFor(() => expect(result.current.available).toBe(true));
    act(() => result.current.generate());
    await waitFor(() => expect(result.current.proposal).not.toBeNull());

    act(() => result.current.toggleTag("tag-0"));

    expect(onUpdate).toHaveBeenCalledWith({ etsy: { tags: [] } });
  });

  it("does not add a 14th tag", async () => {
    const onUpdate = vi.fn();
    mockWorkspace();
    mockReadiness({ ready: true });
    const body = proposal();
    vi.spyOn(seoApi, "requestSeoProposal").mockResolvedValue({ kind: "success", proposal: body });
    const thirteen = Array.from({ length: 13 }, (_, i) => `existing-${i}`);

    const { result } = renderHook(() =>
      useAiSeoMode(detail({ etsy: { ...detail().etsy, tags: thirteen } }), onUpdate, vi.fn()),
    );
    await waitFor(() => expect(result.current.available).toBe(true));
    act(() => result.current.generate());
    await waitFor(() => expect(result.current.proposal).not.toBeNull());

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
    expect(loadStoredProposal({ workspace: "Pine & Thread", listing: "take-a-hike" })).toBeNull();
  });
});

describe("useAiSeoMode stale state", () => {
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
      { workspace: "Pine & Thread", listing: "take-a-hike" },
      toStoredProposal(body, detail()),
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
      { workspace: "Pine & Thread", listing: "take-a-hike" },
      toStoredProposal(body, detail()),
    );

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));
    await waitFor(() => expect(result.current.available).toBe(true));

    expect(result.current.proposal).toBeNull();
  });
});
