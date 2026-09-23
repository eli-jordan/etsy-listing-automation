import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as seoApi from "../../../api/seo";
import type { SaveState } from "../../../hooks/useAutosave";
import type { ListingDetail } from "../../../types";
import type { AiSeoMode } from "./useAiSeoMode";
import { useAutoDesignBrief } from "./useAutoDesignBrief";

/**
 * PRD 68's chain, at the seam where its two rules actually live: *when* a
 * request is allowed to go out, and *what* happens to the answer.
 *
 * `useAiSeoMode` is a stub here rather than the real hook. This file's
 * subject is the chain's own decisions, and driving the real hook would mean
 * standing up its readiness endpoint, its workspace call and its local
 * storage just to observe that `generate()` was eventually called --
 * `useAiSeoMode.test.ts` already owns all of that.
 */

afterEach(() => {
  vi.restoreAllMocks();
});

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
      tags: [],
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
    pricing_plan_name: null,
    resolved_prices: [],
    description_composed: "",
    ...over,
  };
}

const DESIGN = { default: "../../designs/take-a-hike.png" };

function aiSeoStub(over: Partial<AiSeoMode> = {}): AiSeoMode {
  return {
    available: true,
    requirements: [],
    reason: null,
    phase: "idle",
    proposal: null,
    stale: false,
    generate: vi.fn(),
    cancel: vi.fn(),
    chooseTitle: vi.fn(),
    rejectTitle: vi.fn(),
    chooseLead: vi.fn(),
    rejectLead: vi.fn(),
    toggleTag: vi.fn(),
    acceptBestTags: vi.fn(),
    closeTags: vi.fn(),
    ...over,
  };
}

interface Props {
  detail: ListingDetail;
  aiSeo?: AiSeoMode;
  save?: SaveState;
  onUpdate?: (patch: Record<string, unknown>) => void;
  onFlush?: () => void;
}

function setup(initial: Props) {
  const onUpdate = initial.onUpdate ?? vi.fn();
  const onFlush = initial.onFlush ?? vi.fn();
  const view = renderHook(
    (props: Props) =>
      useAutoDesignBrief(
        props.detail,
        onUpdate,
        onFlush,
        props.aiSeo ?? aiSeoStub(),
        props.save ?? { kind: "saved", savedAt: 0 },
      ),
    { initialProps: initial },
  );
  return { ...view, onUpdate, onFlush };
}

function drafts(brief = "Retro sunset mountains.") {
  return vi
    .spyOn(seoApi, "requestDesignBrief")
    .mockResolvedValue({ kind: "success", brief } as never);
}

// ------------------------------------------------------------- what arms it

it("asks for nothing when an editor simply opens on a design with no brief", async () => {
  const request = drafts();

  setup({ detail: detail({ design: DESIGN }) });
  await Promise.resolve();

  expect(request).not.toHaveBeenCalled();
});

it("drafts a brief when a design is attached to a listing that has none", async () => {
  const request = drafts("Retro sunset mountains.");
  const { rerender, onUpdate, onFlush } = setup({ detail: detail() });

  rerender({ detail: detail({ design: DESIGN }) });

  await waitFor(() => expect(onUpdate).toHaveBeenCalledWith({ brief: "Retro sunset mountains." }));
  expect(request).toHaveBeenCalledWith("take-a-hike", expect.anything());
  expect(onFlush).toHaveBeenCalled();
});

it("leaves a brief the seller already wrote completely alone", async () => {
  const request = drafts();
  const { rerender } = setup({ detail: detail({ brief: "Mine." }) });

  rerender({ detail: detail({ brief: "Mine.", design: DESIGN }) });
  await Promise.resolve();

  expect(request).not.toHaveBeenCalled();
});

it("does not re-arm when an unrelated field changes", async () => {
  const request = drafts();
  const { rerender } = setup({ detail: detail({ design: DESIGN }) });

  rerender({ detail: detail({ design: DESIGN, colors: ["black", "navy"] }) });
  await Promise.resolve();

  expect(request).not.toHaveBeenCalled();
});

it("treats a reordered design map as the same design", async () => {
  const request = drafts();
  const both = { "on-light": "a.png", "on-dark": "b.png" };
  const { rerender } = setup({ detail: detail({ design: both }) });

  rerender({ detail: detail({ design: { "on-dark": "b.png", "on-light": "a.png" } }) });
  await Promise.resolve();

  expect(request).not.toHaveBeenCalled();
});

// ----------------------------------------------------- waiting to be saved

it("waits for an unnamed draft to be saved before asking for anything", async () => {
  const request = drafts();
  const { result, rerender } = setup({
    detail: detail({ name: "" }),
    save: { kind: "unnamed" },
  });

  rerender({ detail: detail({ name: "", design: DESIGN }), save: { kind: "unnamed" } });

  await waitFor(() => expect(result.current.waiting).toBe(true));
  expect(result.current.phase).toBe("idle");
  expect(request).not.toHaveBeenCalled();
});

it("asks as soon as naming has saved the listing", async () => {
  const request = drafts();
  const { rerender } = setup({ detail: detail({ name: "" }), save: { kind: "unnamed" } });

  rerender({ detail: detail({ name: "", design: DESIGN }), save: { kind: "unnamed" } });
  rerender({
    detail: detail({ name: "take-a-hike", design: DESIGN }),
    save: { kind: "saved", savedAt: 0 },
  });

  await waitFor(() => expect(request).toHaveBeenCalledWith("take-a-hike", expect.anything()));
});

// --------------------------------------------------------------- once only

it("spends exactly one request per attach", async () => {
  const request = drafts();
  const { rerender } = setup({ detail: detail() });

  rerender({ detail: detail({ design: DESIGN }) });
  await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
  rerender({ detail: detail({ design: DESIGN, colors: ["navy"] }) });
  rerender({ detail: detail({ design: DESIGN, colors: ["moss"] }) });

  expect(request).toHaveBeenCalledTimes(1);
});

it("does not retry after a failure, and says so", async () => {
  const request = vi
    .spyOn(seoApi, "requestDesignBrief")
    .mockResolvedValue({ kind: "failed" } as never);
  const { result, rerender } = setup({ detail: detail() });

  rerender({ detail: detail({ design: DESIGN }) });

  await waitFor(() => expect(result.current.phase).toBe("failed"));
  rerender({ detail: detail({ design: DESIGN, colors: ["navy"] }) });
  expect(request).toHaveBeenCalledTimes(1);
});

it("re-arms when a different design is attached", async () => {
  const request = drafts();
  const { rerender } = setup({ detail: detail() });

  rerender({ detail: detail({ design: DESIGN }) });
  await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
  rerender({ detail: detail({ design: { default: "../../designs/other.png" } }) });

  await waitFor(() => expect(request).toHaveBeenCalledTimes(2));
});

// ------------------------------------------------------ the seller's brief

it("abandons the draft when the seller types their own brief", async () => {
  let abortedSignal: AbortSignal | undefined;
  vi.spyOn(seoApi, "requestDesignBrief").mockImplementation(
    (_name: string, signal: AbortSignal) =>
      new Promise((resolve) => {
        abortedSignal = signal;
        signal.addEventListener("abort", () => resolve({ kind: "cancelled" }));
      }),
  );
  const { result, rerender, onUpdate } = setup({ detail: detail() });

  rerender({ detail: detail({ design: DESIGN }) });
  await waitFor(() => expect(result.current.phase).toBe("drafting"));

  rerender({ detail: detail({ design: DESIGN, brief: "I will write it myself." }) });

  await waitFor(() => expect(abortedSignal?.aborted).toBe(true));
  expect(onUpdate).not.toHaveBeenCalled();
  await waitFor(() => expect(result.current.phase).toBe("idle"));
});

// ---------------------------------------------------------- the generation

it("starts SEO generation once the drafted brief has made AI Mode available", async () => {
  drafts();
  const unavailable = aiSeoStub({ available: false });
  const { rerender } = setup({ detail: detail(), aiSeo: unavailable });

  rerender({ detail: detail({ design: DESIGN }), aiSeo: unavailable });
  await waitFor(() => expect(seoApi.requestDesignBrief).toHaveBeenCalled());
  expect(unavailable.generate).not.toHaveBeenCalled();

  const available = aiSeoStub();
  rerender({ detail: detail({ design: DESIGN, brief: "Drafted." }), aiSeo: available });

  await waitFor(() => expect(available.generate).toHaveBeenCalledTimes(1));
});

it("never starts generation twice for one drafted brief", async () => {
  drafts();
  const aiSeo = aiSeoStub();
  const { rerender } = setup({ detail: detail(), aiSeo });

  rerender({ detail: detail({ design: DESIGN }), aiSeo });
  await waitFor(() => expect(aiSeo.generate).toHaveBeenCalledTimes(1));
  rerender({ detail: detail({ design: DESIGN, brief: "Drafted." }), aiSeo });
  rerender({ detail: detail({ design: DESIGN, brief: "Drafted." }), aiSeo });

  expect(aiSeo.generate).toHaveBeenCalledTimes(1);
});

it("does not start generation after a failed draft", async () => {
  vi.spyOn(seoApi, "requestDesignBrief").mockResolvedValue({ kind: "failed" } as never);
  const aiSeo = aiSeoStub();
  const { result, rerender } = setup({ detail: detail(), aiSeo });

  rerender({ detail: detail({ design: DESIGN }), aiSeo });

  await waitFor(() => expect(result.current.phase).toBe("failed"));
  expect(aiSeo.generate).not.toHaveBeenCalled();
});

describe("cancellation", () => {
  it("aborts an in-flight draft when the editor unmounts", async () => {
    let signal: AbortSignal | undefined;
    vi.spyOn(seoApi, "requestDesignBrief").mockImplementation(
      (_name: string, incoming: AbortSignal) =>
        new Promise((resolve) => {
          signal = incoming;
          incoming.addEventListener("abort", () => resolve({ kind: "cancelled" }));
        }),
    );
    const { rerender, unmount } = setup({ detail: detail() });

    rerender({ detail: detail({ design: DESIGN }) });
    await waitFor(() => expect(signal).toBeDefined());
    unmount();

    expect(signal?.aborted).toBe(true);
  });
});
