import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SaveState } from "../../../hooks/useAutosave";
import {
  aiRunSummary,
  briefEvent,
  type FakeAiRuns,
  fakeAiRuns,
  phaseEvent,
  proposalEvent,
  queriesEvent,
  stepEvent,
} from "../../../test/aiRuns";
import type { ListingDetail, MarketSnapshot, SeoProposalResponse } from "../../../types";
import { type AiRunHandlers, useAiRun } from "./useAiRun";

/**
 * The editor's side of an AI run (market-seo.md, *AI runs*): starting one,
 * following its events into `steps`, `queries`, `market` and `proposal`,
 * reattaching after a reload, cancelling -- and PRD 68's auto chain, which
 * a design pick arms and the first successful save fires.
 *
 * The server is `test/aiRuns.ts`'s stand-in at `api/aiRuns.ts`'s seam; a
 * test pushes the events `ui/airuns/runner.py` would write.
 */

let runs: FakeAiRuns;

beforeEach(() => {
  runs = fakeAiRuns();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function detail(over: Partial<ListingDetail> = {}): ListingDetail {
  return {
    garment_profile: "comfort-colors-1717",
    design: { default: "../../designs/take-a-hike.png" },
    colors: ["black"],
    brief: "A relaxed hiking tee.",
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
    modified_at: "2026-09-25T10:00:00Z",
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

function proposal(): SeoProposalResponse {
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
      etsy_category: "",
      materials: [],
      colors: ["black"],
      garment_brand: "Comfort Colors",
      garment_model: "1717",
      garment_profile: "comfort-colors-1717",
      design: { default: "../../designs/take-a-hike.png" },
      design_content_hash: null,
    },
    generated_at: "2026-09-25T10:00:30Z",
    expires_at: "2026-09-26T10:00:30Z",
  };
}

function snapshot(): MarketSnapshot {
  return {
    queries: ["retro hiking shirt", "mountain sunset tee", "hiking gift shirt"],
    found: 58,
    scored: 20,
    searched_at: "2026-09-25T10:00:20Z",
    listings: [],
    phrases: [],
    relaxed: false,
    empty: false,
    block: "",
  };
}

const saved = (at: number): SaveState => ({ kind: "saved", savedAt: at });

interface Props {
  detail: ListingDetail;
  save?: SaveState;
}

function setup(initial: Partial<Props> = {}, handlers: AiRunHandlers = {}) {
  const props: Props = { detail: detail(), save: saved(1), ...initial };
  return renderHook((p: Props) => useAiRun(p.detail, p.save, handlers), { initialProps: props });
}

async function started(view: ReturnType<typeof setup>, draftBrief = false) {
  act(() => view.result.current.start({ draftBrief }));
  await waitFor(() => expect(view.result.current.phase).toBe("running"));
}

describe("useAiRun starting and following a run", () => {
  it("is idle, with no steps, when the listing has no run", async () => {
    const { result } = setup();

    await waitFor(() => expect(runs.find).toHaveBeenCalledWith("take-a-hike"));
    expect(result.current.phase).toBe("idle");
    expect(result.current.steps).toEqual([]);
    expect(result.current.busy).toBe(false);
  });

  it("starts a run for the listing and follows its stream", async () => {
    const view = setup();

    act(() => view.result.current.start({ draftBrief: false }));
    expect(view.result.current.busy).toBe(true);
    await waitFor(() => expect(view.result.current.phase).toBe("running"));

    expect(runs.start).toHaveBeenCalledWith("take-a-hike", { draftBrief: false });
    expect(view.result.current.autoNotice).toBe(false);
    expect(runs.stream().runId).toBe("run-1");
    expect(view.result.current.steps.map((s) => [s.id, s.state])).toEqual([
      ["brief", "skipped"],
      ["market", "pending"],
      ["seo", "pending"],
    ]);
  });

  it("dates Generating for… from the run's own start time", async () => {
    runs.start.mockResolvedValue({
      kind: "started",
      run: aiRunSummary({ created_at: "2026-09-25T10:00:00Z" }),
    });
    const view = setup();

    await started(view);

    expect(view.result.current.startedAt).toBe(Date.parse("2026-09-25T10:00:00Z"));
  });

  it("keeps the latest step event for each node, in chain order", async () => {
    const view = setup();
    await started(view);

    runs.emit(
      stepEvent("market", "active", "Choosing Etsy searches from the brief"),
      stepEvent("market", "active", "Searching Etsy for 3 phrases…"),
    );

    expect(view.result.current.steps).toEqual([
      { id: "brief", state: "skipped", detail: "You wrote the brief, so it was kept" },
      { id: "market", state: "active", detail: "Searching Etsy for 3 phrases…" },
      { id: "seo", state: "pending", detail: null },
    ]);
  });

  it("holds the searches and the market snapshot as they arrive", async () => {
    const view = setup();
    await started(view);

    runs.emit(queriesEvent(snapshot().queries));
    expect(view.result.current.queries).toEqual(snapshot().queries);
    expect(view.result.current.market).toBeNull();

    runs.emit({ type: "market", seq: 99, snapshot: snapshot() });
    expect(view.result.current.market).toEqual(snapshot());
  });

  it("hands a written brief to the editor, and keeps quiet about one it did not write", async () => {
    const onBrief = vi.fn();
    const view = setup({}, { onBrief });
    await started(view, true);

    runs.emit(briefEvent("Retro sunset over mountains.", false));
    expect(onBrief).not.toHaveBeenCalled();

    runs.emit(briefEvent("Retro sunset over mountains."));
    expect(onBrief).toHaveBeenCalledWith("Retro sunset over mountains.");
  });

  it("hands the proposal over as the plain response, without the event's own fields", async () => {
    const onProposal = vi.fn();
    const view = setup({}, { onProposal });
    await started(view);

    runs.emit(proposalEvent(proposal()));

    expect(onProposal).toHaveBeenCalledWith(proposal());
    expect(view.result.current.proposal).toEqual(proposal());
  });

  it("ends with the run's phase, and a failure keeps its message", async () => {
    const view = setup();
    await started(view);

    runs.emit(
      stepEvent("market", "failed", "Etsy market search failed: timed out"),
      phaseEvent("failed", "Etsy market search failed: timed out"),
    );
    runs.end();

    expect(view.result.current.phase).toBe("failed");
    expect(view.result.current.busy).toBe(false);
    expect(view.result.current.message).toBe("Etsy market search failed: timed out");
  });

  it("reports a refusal as a failure that names the rule", async () => {
    runs.start.mockResolvedValue({ kind: "refused", reason: "the listing brief is empty" });
    const view = setup();

    act(() => view.result.current.start({ draftBrief: false }));

    await waitFor(() => expect(view.result.current.phase).toBe("failed"));
    expect(view.result.current.message).toBe("the listing brief is empty");
    expect(runs.streams).toEqual([]);
  });

  it("reports a start that could not reach the server as a failure", async () => {
    runs.start.mockRejectedValue(new Error("network down"));
    const view = setup();

    act(() => view.result.current.start({ draftBrief: false }));

    await waitFor(() => expect(view.result.current.phase).toBe("failed"));
    expect(view.result.current.message).toMatch(/could not start/i);
  });

  it("follows the run already active for the listing instead of starting another", async () => {
    runs.start.mockResolvedValue({ kind: "active", runId: "run-0" });
    const view = setup();
    await waitFor(() => expect(runs.find).toHaveBeenCalledTimes(1));
    runs.find.mockResolvedValue(aiRunSummary({ id: "run-0" }));

    act(() => view.result.current.start({ draftBrief: false }));

    await waitFor(() => expect(runs.stream().runId).toBe("run-0"));
    expect(view.result.current.phase).toBe("running");
  });

  it("says so when the stream is lost mid-run", async () => {
    const view = setup();
    await started(view);

    act(() => runs.stream().options.onError?.(new Error("connection reset")));

    expect(view.result.current.phase).toBe("failed");
    expect(view.result.current.message).toMatch(/reload/i);
  });

  it("closes the stream when the editor unmounts, and the run carries on", async () => {
    const view = setup();
    await started(view);

    view.unmount();

    expect(runs.stream().closed).toBe(true);
    expect(runs.cancel).not.toHaveBeenCalled();
  });
});

describe("useAiRun reattaching", () => {
  it("replays a run still in flight after a reload", async () => {
    runs.find.mockResolvedValue(aiRunSummary({ id: "run-7" }));
    const onBrief = vi.fn();
    const view = setup({}, { onBrief });

    await waitFor(() => expect(runs.stream().runId).toBe("run-7"));
    expect(view.result.current.phase).toBe("running");
    runs.emit(
      stepEvent("brief", "done", "Drafted from take-a-hike.png"),
      stepEvent("market", "active", "Searching Etsy for 3 phrases…"),
    );

    expect(view.result.current.steps[1]).toEqual({
      id: "market",
      state: "active",
      detail: "Searching Etsy for 3 phrases…",
    });
  });

  it("replays a run that has just finished, proposal included", async () => {
    runs.find.mockResolvedValue(aiRunSummary({ phase: "done" }));
    const onProposal = vi.fn();
    const view = setup({}, { onProposal });

    await waitFor(() => expect(runs.streams).toHaveLength(1));
    runs.emit(proposalEvent(proposal()), phaseEvent("done"));

    expect(onProposal).toHaveBeenCalledWith(proposal());
    expect(view.result.current.phase).toBe("done");
  });

  it("does not hand over the brief of a run that had already finished", async () => {
    /* The file already has it, or the seller has since changed it: either
       way the listing that loaded is the truth, not the replay. */
    runs.find.mockResolvedValue(aiRunSummary({ phase: "done" }));
    const onBrief = vi.fn();
    setup({}, { onBrief });

    await waitFor(() => expect(runs.streams).toHaveLength(1));
    runs.emit(briefEvent("Drafted an hour ago."), phaseEvent("done"));

    expect(onBrief).not.toHaveBeenCalled();
  });

  it("asks nothing for a listing that is not saved yet", async () => {
    setup({ detail: detail({ name: "" }), save: { kind: "unnamed" } });

    await act(async () => {});
    expect(runs.find).not.toHaveBeenCalled();
  });

  it("stays idle when the reattach check fails", async () => {
    runs.find.mockRejectedValue(new Error("network down"));
    const view = setup();

    await waitFor(() => expect(runs.find).toHaveBeenCalled());
    expect(view.result.current.phase).toBe("idle");
  });
});

describe("useAiRun cancelling", () => {
  it("cancels the run it is following", async () => {
    const view = setup();
    await started(view);

    act(() => view.result.current.cancel());

    expect(runs.cancel).toHaveBeenCalledWith("run-1");
    expect(view.result.current.busy).toBe(true);
    runs.emit(stepEvent("market", "pending", "Cancelled"), phaseEvent("cancelled"));
    expect(view.result.current.phase).toBe("cancelled");
    expect(view.result.current.busy).toBe(false);
  });

  it("does nothing when there is no run to cancel", () => {
    const view = setup();

    act(() => view.result.current.cancel());

    expect(runs.cancel).not.toHaveBeenCalled();
  });

  it("lets the server's own ending win when the run finished first", async () => {
    runs.cancel.mockResolvedValue(false);
    const view = setup();
    await started(view);

    act(() => view.result.current.cancel());
    runs.emit(phaseEvent("done"));

    expect(view.result.current.phase).toBe("done");
  });
});

describe("useAiRun auto chain (PRD 68)", () => {
  /** A pick on a listing with an empty brief, then the saves that follow. */
  function picked(over: Partial<ListingDetail> = {}) {
    const view = setup({ detail: detail({ brief: "", ...over }), save: saved(1) });
    act(() => view.result.current.arm());
    return view;
  }

  it("fires on the first successful save after the pick, drafting the brief", async () => {
    const view = picked();

    view.rerender({ detail: detail({ brief: "" }), save: { kind: "saving" } });
    expect(runs.start).not.toHaveBeenCalled();
    view.rerender({ detail: detail({ brief: "" }), save: saved(2) });

    await waitFor(() =>
      expect(runs.start).toHaveBeenCalledWith("take-a-hike", { draftBrief: true }),
    );
    expect(view.result.current.autoNotice).toBe(true);
  });

  it("does not fire on the save that was already showing when the design was picked", async () => {
    const showing = saved(1);
    const view = setup({ detail: detail({ brief: "" }), save: showing });
    act(() => view.result.current.arm());

    view.rerender({ detail: detail({ brief: "" }), save: showing });

    await act(async () => {});
    expect(runs.start).not.toHaveBeenCalled();
  });

  it("fires only once", async () => {
    const view = picked();

    view.rerender({ detail: detail({ brief: "" }), save: saved(2) });
    await waitFor(() => expect(runs.start).toHaveBeenCalledTimes(1));
    view.rerender({ detail: detail({ brief: "" }), save: saved(3) });

    await act(async () => {});
    expect(runs.start).toHaveBeenCalledTimes(1);
  });

  it("waits for a garment profile before it fires", async () => {
    const view = picked({ garment_profile: "" });

    view.rerender({ detail: detail({ brief: "", garment_profile: "" }), save: saved(2) });
    await act(async () => {});
    expect(runs.start).not.toHaveBeenCalled();

    view.rerender({ detail: detail({ brief: "" }), save: saved(3) });
    await waitFor(() => expect(runs.start).toHaveBeenCalledTimes(1));
  });

  it("waits for the save that carries the garment profile, not the edit that chose it", async () => {
    /* Found against a real workspace: the create saved without a garment
       profile; choosing one then changed the editor at once, but the save
       showing was still the create's -- the file had no profile yet. */
    const created = saved(2);
    const view = picked({ garment_profile: "" });
    view.rerender({ detail: detail({ brief: "", garment_profile: "" }), save: created });
    await act(async () => {});

    view.rerender({ detail: detail({ brief: "" }), save: created });
    await act(async () => {});
    expect(runs.start).not.toHaveBeenCalled();

    view.rerender({ detail: detail({ brief: "" }), save: saved(3) });
    await waitFor(() => expect(runs.start).toHaveBeenCalledTimes(1));
  });

  it("waits for a name before it fires", async () => {
    const view = picked({ name: "" });

    view.rerender({ detail: detail({ brief: "", name: "" }), save: { kind: "unsaved" } });
    await act(async () => {});
    expect(runs.start).not.toHaveBeenCalled();

    view.rerender({ detail: detail({ brief: "" }), save: saved(2) });
    await waitFor(() => expect(runs.start).toHaveBeenCalledTimes(1));
  });

  it("skips the brief when the seller wrote one before it fired", async () => {
    const view = picked();

    view.rerender({ detail: detail({ brief: "My own words." }), save: saved(2) });

    await waitFor(() =>
      expect(runs.start).toHaveBeenCalledWith("take-a-hike", { draftBrief: false }),
    );
  });

  it("is not armed by a pick on a listing that already has a brief", async () => {
    const view = setup({ detail: detail({ brief: "Already here." }), save: saved(1) });
    act(() => view.result.current.arm());

    view.rerender({ detail: detail({ brief: "Already here." }), save: saved(2) });

    await act(async () => {});
    expect(runs.start).not.toHaveBeenCalled();
  });

  it("never fires again after a failure without a new pick, and a new pick re-arms it", async () => {
    runs.start.mockResolvedValue({ kind: "refused", reason: "no AI provider is ready" });
    const view = picked();
    view.rerender({ detail: detail({ brief: "" }), save: saved(2) });
    await waitFor(() => expect(view.result.current.phase).toBe("failed"));

    view.rerender({ detail: detail({ brief: "" }), save: saved(3) });
    await act(async () => {});
    expect(runs.start).toHaveBeenCalledTimes(1);

    act(() => view.result.current.arm());
    view.rerender({ detail: detail({ brief: "" }), save: saved(4) });
    await waitFor(() => expect(runs.start).toHaveBeenCalledTimes(2));
  });

  it("is disarmed by leaving the editor", async () => {
    const view = picked();

    view.unmount();

    await act(async () => {});
    expect(runs.start).not.toHaveBeenCalled();
  });
});
