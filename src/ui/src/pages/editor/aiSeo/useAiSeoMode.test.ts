import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as seoApi from "../../../api/seo";
import {
  AI_RUN_CREATED_AT,
  aiRunSummary,
  briefEvent,
  type FakeAiRuns,
  fakeAiRuns,
  listingProposal,
  phaseEvent,
  proposalEvent,
} from "../../../test/aiRuns";
import { deferred } from "../../../test/helpers";
import type { ListingDetail, ListingProposal, SeoReadinessResponse } from "../../../types";
import { BATCH_POLL_MS, useAiSeoMode } from "./useAiSeoMode";
import { listingDetail, listingEtsy } from "../../../test/listings";

function detail(over: Partial<ListingDetail> = {}): ListingDetail {
  return listingDetail({
    brief: "A relaxed hiking tee.",
    garment_materials: ["ring-spun cotton"],
    garment_product_type: "tee",
    garment_brand: "Comfort Colors",
    garment_model: "1717",
    etsy: listingEtsy({ title: "Take A Hike Tee", section: "Graphic Tees" }),
    design_content_hash: null,
    ...over,
  });
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
    mockReadiness({ ready: true, batch_pending: false, deploying: false });

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
    const readiness = vi
      .spyOn(seoApi, "getSeoReadiness")
      .mockResolvedValue({ ready: true, batch_pending: false, deploying: false });

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));

    await waitFor(() => expect(result.current.available).toBe(true));
    expect(readiness).toHaveBeenCalledWith("take-a-hike");
    expect(result.current.reason).toBeNull();
  });

  /** Holds the readiness answer back, so a case sees "checking" before it settles. */
  function pendingReadiness() {
    const answer = deferred<SeoReadinessResponse>();
    const readiness = vi.spyOn(seoApi, "getSeoReadiness").mockReturnValue(answer.promise);
    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));
    expect(result.current.available).toBe(false);
    expect(result.current.reason).toBe("Checking AI setup...");
    expect(readiness).toHaveBeenCalledWith("take-a-hike");
    return { answer, result };
  }

  it("stays unavailable when the readiness endpoint says not ready, and says why", async () => {
    const { answer, result } = pendingReadiness();

    await act(async () => {
      answer.resolve({
        ready: false,
        reason: "no AI provider is ready",
        batch_pending: false,
        deploying: false,
      });
      await answer.promise;
    });

    await waitFor(() => expect(result.current.reason).toBe("no AI provider is ready"));
    expect(result.current.available).toBe(false);
    expect(result.current.requirements.at(-1)).toEqual({
      label: "SEO prompt and AI provider ready",
      ready: false,
    });
  });

  it("stays unavailable when the readiness check itself fails, and says so", async () => {
    const { answer, result } = pendingReadiness();

    await act(async () => {
      answer.reject(new Error("network down"));
      await answer.promise.catch(() => undefined);
    });

    await waitFor(() => expect(result.current.reason).toBe("Could not check AI setup."));
    expect(result.current.available).toBe(false);
  });
});

describe("useAiSeoMode generation", () => {
  it("starts a run without drafting, and keeps the proposal it delivers", async () => {
    mockReadiness({ ready: true, batch_pending: false, deploying: false });
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
    mockReadiness({ ready: true, batch_pending: false, deploying: false });

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));
    await waitFor(() => expect(result.current.available).toBe(true));
    act(() => result.current.generate());

    await waitFor(() => expect(result.current.run.steps).toHaveLength(3));
    // The server's start, which the elapsed-time readout counts from.
    expect(result.current.startedAt).toBe(Date.parse(AI_RUN_CREATED_AT));
  });

  it("moves to a failed phase, says why, and stores nothing when the run fails", async () => {
    mockReadiness({ ready: true, batch_pending: false, deploying: false });

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
    mockReadiness({ ready: true, batch_pending: false, deploying: false });

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
    mockReadiness({ ready: true, batch_pending: false, deploying: false });
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

describe("useAiSeoMode while a batch owns the listing", () => {
  const BATCH = "This listing is drafting in a batch. AI Mode is back once that is done.";

  afterEach(() => vi.useRealTimers());

  it("is disabled with the hint, follows the batch run live, and is back once it is done", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const readiness = vi
      .spyOn(seoApi, "getSeoReadiness")
      .mockResolvedValue({ ready: false, reason: BATCH, batch_pending: true, deploying: false });
    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));
    await waitFor(() => expect(result.current.reason).toBe(BATCH));
    expect(result.current.available).toBe(false);
    expect(runs.streams).toHaveLength(0);

    // The row's turn comes while the editor is open.
    runs.find.mockResolvedValue(aiRunSummary({ id: "batch-run", origin: "batch" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BATCH_POLL_MS);
    });
    await waitFor(() => expect(runs.streams).toHaveLength(1));
    expect(runs.stream().runId).toBe("batch-run");
    expect(result.current.run.busy).toBe(true);

    runs.emit(proposalEvent(proposal()), phaseEvent("done"));
    expect(result.current.proposal).not.toBeNull();
    readiness.mockResolvedValue({ ready: true, batch_pending: false, deploying: false });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BATCH_POLL_MS);
    });

    await waitFor(() => expect(result.current.available).toBe(true));
    expect(runs.streams).toHaveLength(1);
  });
});

describe("useAiSeoMode while a deploy holds the listing", () => {
  const DEPLOYING = "This listing is deploying. AI Mode is back once the deploy finishes.";

  afterEach(() => vi.useRealTimers());

  it("is disabled with the hint and asks again until the deploy lets go", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const readiness = vi.spyOn(seoApi, "getSeoReadiness").mockResolvedValue({
      ready: false,
      reason: DEPLOYING,
      batch_pending: false,
      deploying: true,
    });
    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));
    await waitFor(() => expect(result.current.reason).toBe(DEPLOYING));
    expect(result.current.available).toBe(false);

    readiness.mockResolvedValue({ ready: true, batch_pending: false, deploying: false });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BATCH_POLL_MS);
    });

    await waitFor(() => expect(result.current.available).toBe(true));
    expect(runs.streams).toHaveLength(0);
  });
});

describe("useAiSeoMode and the auto chain's brief", () => {
  it("puts a drafted brief into an empty field without saving it again", async () => {
    mockReadiness({ ready: true, batch_pending: false, deploying: false });
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
    mockReadiness({ ready: true, batch_pending: false, deploying: false });
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
  mockReadiness({ ready: true, batch_pending: false, deploying: false });
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
    mockReadiness({ ready: true, batch_pending: false, deploying: false });
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
    mockReadiness({ ready: true, batch_pending: false, deploying: false });
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

describe("useAiSeoMode proposal reconciliation", () => {
  it("keeps a newer staleness judgment when an older resolution response arrives", async () => {
    const { result, rerender, body } = await readyHookWithProposal();
    let finish!: (value: ListingProposal | null) => void;
    runs.resolveProposal.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    act(() => result.current.rejectTitle());
    const stale = {
      ...body,
      stale: { is_stale: true, reasons: ["brief edited since"] },
    };
    runs.cached.proposal = stale;
    rerender(detail({ brief: "Edited brief", modified_at: "2026-09-17T10:10:00Z" }));
    await waitFor(() => expect(result.current.staleReason).toBe("brief edited since"));

    runs.cached.proposal = {
      ...stale,
      resolution: { ...body.resolution, title: "dismissed" },
    };
    await act(async () =>
      finish({
        ...body,
        resolution: { ...body.resolution, title: "dismissed" },
      }),
    );

    expect(result.current.staleReason).toBe("brief edited since");
    expect(result.current.proposal?.resolution.title).toBe("dismissed");
  });
  it("finishes queued choices on their listing after the editor navigates away", async () => {
    const { result, rerender, body } = await readyHookWithProposal();
    let finish!: (value: ListingProposal | null) => void;
    runs.resolveProposal.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    act(() => {
      result.current.rejectTitle();
      result.current.rejectLead();
    });
    runs.cached.proposal = null;
    rerender(detail({ name: "another-listing" }));
    await waitFor(() => expect(runs.loadProposal).toHaveBeenCalledWith("another-listing"));
    const acknowledged = {
      ...body,
      resolution: { ...body.resolution, title: "dismissed" as const },
    };
    runs.cached.proposal = acknowledged;
    await act(async () => finish(acknowledged));

    await waitFor(() => expect(runs.resolveProposal).toHaveBeenCalledTimes(2));
    expect(runs.resolveProposal).toHaveBeenLastCalledWith("take-a-hike", {
      generated_at: body.generated_at,
      lead: "dismissed",
    });
    expect(result.current.proposal).toBeNull();
  });
  it("keeps later choices closed when an earlier resolution is acknowledged", async () => {
    const { result, body } = await readyHookWithProposal();
    let finish!: (value: ListingProposal | null) => void;
    runs.resolveProposal.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );

    act(() => {
      result.current.rejectTitle();
      result.current.rejectLead();
    });
    expect(result.current.proposal?.resolution).toEqual({
      title: "dismissed",
      lead: "dismissed",
      tags: "pending",
    });
    expect(runs.resolveProposal).toHaveBeenCalledTimes(1);
    runs.cached.proposal = { ...body, resolution: { ...body.resolution, title: "dismissed" } };
    await act(async () => finish(runs.cached.proposal));

    await waitFor(() => expect(runs.cached.proposal?.resolution.lead).toBe("dismissed"));
    expect(result.current.proposal?.resolution).toEqual({
      title: "dismissed",
      lead: "dismissed",
      tags: "pending",
    });
  });

  it("ignores an old resolution response after a replacement proposal arrives", async () => {
    const { result, rerender, body } = await readyHookWithProposal();
    let finish!: (value: ListingProposal | null) => void;
    runs.resolveProposal.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    act(() => {
      result.current.rejectTitle();
      result.current.rejectLead();
    });
    const fresh = proposal({ generated_at: "2026-09-24T00:00:00Z" });
    runs.cached.proposal = fresh;
    rerender(detail({ modified_at: "2026-09-17T10:10:00Z" }));
    await waitFor(() => expect(result.current.proposal).toEqual(fresh));

    await act(async () =>
      finish({ ...body, resolution: { ...body.resolution, title: "dismissed" } }),
    );
    expect(result.current.proposal).toEqual(fresh);
    expect(runs.resolveProposal).toHaveBeenCalledTimes(1);
  });

  it("restores the server drawer state if a resolution fails", async () => {
    const { result, body } = await readyHookWithProposal();
    runs.resolveProposal.mockRejectedValueOnce(new Error("offline"));

    act(() => result.current.rejectTitle());
    expect(result.current.proposal?.resolution.title).toBe("dismissed");

    await waitFor(() => expect(result.current.proposal).toEqual(body));
  });

  it("ignores a late cache read once a live proposal has arrived", async () => {
    mockReadiness({ ready: true, batch_pending: false, deploying: false });
    let finish!: (value: ListingProposal | null) => void;
    runs.loadProposal.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));
    await waitFor(() => expect(result.current.available).toBe(true));
    act(() => result.current.generate());
    const fresh = proposal({ generated_at: "2026-09-24T00:00:00Z" });
    await delivers(fresh);
    await waitFor(() => expect(result.current.proposal).toEqual(fresh));

    await act(async () => finish(proposal()));
    expect(result.current.proposal).toEqual(fresh);
  });
  it("keeps a chosen drawer closed when a save reads the proposal before resolution finishes", async () => {
    const { result, rerender, body } = await readyHookWithProposal();
    let finish!: (value: ListingProposal | null) => void;
    runs.resolveProposal.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );

    let refresh!: (value: ListingProposal | null) => void;
    runs.loadProposal.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          refresh = resolve;
        }),
    );
    act(() => result.current.chooseTitle("Title B"));
    rerender(detail({ modified_at: "2026-09-17T10:10:00Z" }));
    await waitFor(() => expect(runs.loadProposal).toHaveBeenCalledTimes(2));
    await act(async () => refresh(body));

    expect(result.current.proposal?.resolution.title).toBe("accepted");
    await act(async () =>
      finish({
        ...body,
        resolution: { ...body.resolution, title: "accepted" },
      }),
    );
  });
});

describe("useAiSeoMode stale state", () => {
  it("names what changed, from the server, and keeps every choice usable", async () => {
    mockReadiness({ ready: true, batch_pending: false, deploying: false });
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
    mockReadiness({ ready: true, batch_pending: false, deploying: false });
    const body = proposal();
    runs.cached.proposal = body;

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));

    await waitFor(() => expect(result.current.proposal).toEqual(body));
    expect(runs.loadProposal).toHaveBeenCalledWith("take-a-hike");
  });

  it("keeps a resolved section closed", async () => {
    mockReadiness({ ready: true, batch_pending: false, deploying: false });
    runs.cached.proposal = proposal({
      resolution: { title: "accepted", tags: "pending", lead: "dismissed" },
    });

    const { result } = renderHook(() => useAiSeoMode(detail(), vi.fn(), vi.fn()));

    await waitFor(() => expect(result.current.proposal?.resolution.title).toBe("accepted"));
    expect(result.current.proposal?.resolution.lead).toBe("dismissed");
  });

  it("has nothing pending when every section of the cached proposal is resolved", async () => {
    mockReadiness({ ready: true, batch_pending: false, deploying: false });
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
    mockReadiness({ ready: true, batch_pending: false, deploying: false });
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
