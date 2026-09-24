import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import * as seoApi from "../../../api/seo";
import type { AiSeoMode } from "./useAiSeoMode";
import { useAutoDesignBrief } from "./useAutoDesignBrief";

/**
 * PRD 68's chain, at the seam where its rules live: what the pick sends, what
 * happens to the answer, and what stops a drafted brief landing on top of the
 * seller's own words.
 *
 * `useAiSeoMode` is a stub rather than the real hook. This file's subject is
 * the chain's own decisions, and driving the real hook would mean standing up
 * its readiness endpoint, its workspace call and its local storage just to
 * observe that `generate()` was eventually called -- `useAiSeoMode.test.ts`
 * already owns all of that.
 */

afterEach(() => {
  vi.restoreAllMocks();
});

const REF = "../../designs/take-a-hike.png";

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
  brief?: string;
  aiSeo?: AiSeoMode;
}

function setup(initial: Props = {}) {
  const onUpdate = vi.fn();
  const onFlush = vi.fn();
  const view = renderHook(
    (props: Props) =>
      useAutoDesignBrief(props.brief ?? "", onUpdate, onFlush, props.aiSeo ?? aiSeoStub()),
    { initialProps: initial },
  );
  return { ...view, onUpdate, onFlush };
}

function drafts(brief = "Retro sunset mountains.") {
  return vi
    .spyOn(seoApi, "requestDesignBrief")
    .mockResolvedValue({ kind: "success", brief } as never);
}

// ------------------------------------------------------------ what it sends

it("asks for nothing until a design is actually picked", async () => {
  const request = drafts();

  setup();
  await Promise.resolve();

  expect(request).not.toHaveBeenCalled();
});

it("sends only the design, as a workspace path -- no listing, no garment", async () => {
  const request = drafts();
  const { result } = setup();

  act(() => result.current.start(REF));

  await waitFor(() =>
    expect(request).toHaveBeenCalledWith("designs/take-a-hike.png", expect.anything()),
  );
});

it("writes the drafted brief through the ordinary autosave path", async () => {
  drafts("Retro sunset mountains.");
  const { result, onUpdate, onFlush } = setup();

  act(() => result.current.start(REF));

  await waitFor(() => expect(onUpdate).toHaveBeenCalledWith({ brief: "Retro sunset mountains." }));
  expect(onFlush).toHaveBeenCalled();
});

it("reports itself drafting while the request is in flight", async () => {
  vi.spyOn(seoApi, "requestDesignBrief").mockImplementation(() => new Promise(() => {}));
  const { result } = setup();

  act(() => result.current.start(REF));

  await waitFor(() => expect(result.current.phase).toBe("drafting"));
});

// --------------------------------------------------------- the seller's brief

it("does not ask at all when the listing already has a brief", async () => {
  const request = drafts();
  const { result } = setup({ brief: "Mine." });

  act(() => result.current.start(REF));
  await Promise.resolve();

  expect(request).not.toHaveBeenCalled();
});

it("throws the draft away if the seller wrote a brief while it was running", async () => {
  let resolveWith: ((outcome: seoApi.DesignBriefOutcome) => void) | undefined;
  vi.spyOn(seoApi, "requestDesignBrief").mockImplementation(
    () =>
      new Promise((resolve) => {
        resolveWith = resolve;
      }),
  );
  const { result, rerender, onUpdate } = setup();

  act(() => result.current.start(REF));
  await waitFor(() => expect(result.current.phase).toBe("drafting"));

  // A minute passes; the seller writes their own brief, which is the
  // authority on the design.
  rerender({ brief: "I wrote this myself." });
  await act(async () => {
    resolveWith?.({ kind: "success", brief: "The model's version." });
  });

  expect(onUpdate).not.toHaveBeenCalled();
  expect(result.current.phase).toBe("idle");
});

// ----------------------------------------------------------------- failures

it("reports a failure and does not retry on its own", async () => {
  const request = vi
    .spyOn(seoApi, "requestDesignBrief")
    .mockResolvedValue({ kind: "failed" } as never);
  const { result, rerender, onUpdate } = setup();

  act(() => result.current.start(REF));

  await waitFor(() => expect(result.current.phase).toBe("failed"));
  rerender({ brief: "" });
  rerender({ brief: "" });
  expect(request).toHaveBeenCalledTimes(1);
  expect(onUpdate).not.toHaveBeenCalled();
});

it("treats a cancelled draft as nothing having happened", async () => {
  vi.spyOn(seoApi, "requestDesignBrief").mockResolvedValue({ kind: "cancelled" } as never);
  const { result, onUpdate } = setup();

  act(() => result.current.start(REF));

  await waitFor(() => expect(result.current.phase).toBe("idle"));
  expect(onUpdate).not.toHaveBeenCalled();
});

it("aborts an in-flight draft when the editor unmounts", async () => {
  let signal: AbortSignal | undefined;
  vi.spyOn(seoApi, "requestDesignBrief").mockImplementation(
    (_design: string, incoming: AbortSignal) =>
      new Promise((resolve) => {
        signal = incoming;
        incoming.addEventListener("abort", () => resolve({ kind: "cancelled" }));
      }),
  );
  const { result, unmount } = setup();

  act(() => result.current.start(REF));
  await waitFor(() => expect(signal).toBeDefined());
  unmount();

  expect(signal?.aborted).toBe(true);
});

it("replaces an earlier draft when a second design is picked", async () => {
  const signals: AbortSignal[] = [];
  vi.spyOn(seoApi, "requestDesignBrief").mockImplementation(
    (_design: string, incoming: AbortSignal) => {
      signals.push(incoming);
      return new Promise((resolve) => {
        incoming.addEventListener("abort", () => resolve({ kind: "cancelled" }));
      });
    },
  );
  const { result } = setup();

  act(() => result.current.start(REF));
  act(() => result.current.start("../../designs/other.png"));

  expect(signals).toHaveLength(2);
  expect(signals[0]?.aborted).toBe(true);
  expect(signals[1]?.aborted).toBe(false);
});

// ---------------------------------------------------------------- generation

it("starts SEO generation once the drafted brief has made AI Mode available", async () => {
  drafts();
  const unavailable = aiSeoStub({ available: false });
  const { result, rerender } = setup({ aiSeo: unavailable });

  act(() => result.current.start(REF));
  await waitFor(() => expect(seoApi.requestDesignBrief).toHaveBeenCalled());
  expect(unavailable.generate).not.toHaveBeenCalled();

  const available = aiSeoStub();
  rerender({ brief: "Drafted.", aiSeo: available });

  await waitFor(() => expect(available.generate).toHaveBeenCalledTimes(1));
});

it("never starts generation twice for one drafted brief", async () => {
  drafts();
  const aiSeo = aiSeoStub();
  const { result, rerender } = setup({ aiSeo });

  act(() => result.current.start(REF));
  await waitFor(() => expect(aiSeo.generate).toHaveBeenCalledTimes(1));
  rerender({ brief: "Drafted.", aiSeo });
  rerender({ brief: "Drafted.", aiSeo });

  expect(aiSeo.generate).toHaveBeenCalledTimes(1);
});

it("does not start generation after a failed draft", async () => {
  vi.spyOn(seoApi, "requestDesignBrief").mockResolvedValue({ kind: "failed" } as never);
  const aiSeo = aiSeoStub();
  const { result } = setup({ aiSeo });

  act(() => result.current.start(REF));

  await waitFor(() => expect(result.current.phase).toBe("failed"));
  expect(aiSeo.generate).not.toHaveBeenCalled();
});
