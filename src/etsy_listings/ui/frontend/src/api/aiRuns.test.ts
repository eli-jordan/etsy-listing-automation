import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AiRunsApiError, cancelAiRun, findAiRun, openAiRunStream, startAiRun } from "./aiRuns";
import { api } from "./client";
import type { AiRunSummary } from "../types";

/** `/api/ai/runs` (the implementation plan's Run contract), through the
 * typed client's methods stubbed at the `api` seam -- the same seam
 * `seo.test.ts` uses -- and, for the event stream, a stubbed `fetch`. */

function summary(over: Partial<AiRunSummary> = {}): AiRunSummary {
  return {
    id: "run-1",
    listing: "take-a-hike",
    draft_brief: false,
    phase: "running",
    steps: [
      { id: "brief", state: "skipped", detail: "You wrote the brief, so it was kept" },
      { id: "market", state: "pending", detail: null },
      { id: "seo", state: "pending", detail: null },
    ],
    created_at: "2026-09-25T10:00:00Z",
    finished_at: null,
    ...over,
  };
}

function answer(status: number, data: unknown, error?: unknown) {
  return {
    data: status < 400 ? data : undefined,
    error: status < 400 ? undefined : error,
    response: new Response(null, { status }),
  } as never;
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("startAiRun", () => {
  it("posts the listing and whether to draft the brief, and returns the new run", async () => {
    const post = vi.spyOn(api, "POST").mockResolvedValue(answer(202, summary()));

    await expect(startAiRun("take-a-hike", { draftBrief: true })).resolves.toEqual({
      kind: "started",
      run: summary(),
    });
    expect(post).toHaveBeenCalledWith("/api/ai/runs", {
      body: { listing: "take-a-hike", draft_brief: true },
    });
  });

  it("names the run already active for the listing, so the caller reattaches", async () => {
    vi.spyOn(api, "POST").mockResolvedValue(answer(409, undefined, { active_run: "run-0" }));

    await expect(startAiRun("take-a-hike", { draftBrief: false })).resolves.toEqual({
      kind: "active",
      runId: "run-0",
    });
  });

  it("passes on the readiness rule the server refused with", async () => {
    vi.spyOn(api, "POST").mockResolvedValue(
      answer(409, undefined, { reason: "the listing brief is empty" }),
    );

    await expect(startAiRun("take-a-hike", { draftBrief: false })).resolves.toEqual({
      kind: "refused",
      reason: "the listing brief is empty",
    });
  });

  it("throws for anything else, such as a listing that was never saved", async () => {
    vi.spyOn(api, "POST").mockResolvedValue(answer(404, undefined, { detail: "no listing" }));

    await expect(startAiRun("gone", { draftBrief: false })).rejects.toBeInstanceOf(AiRunsApiError);
  });
});

describe("findAiRun", () => {
  it("returns the listing's current or latest run", async () => {
    const get = vi.spyOn(api, "GET").mockResolvedValue(answer(200, summary()));

    await expect(findAiRun("take-a-hike")).resolves.toEqual(summary());
    expect(get).toHaveBeenCalledWith("/api/ai/runs", {
      params: { query: { listing: "take-a-hike" } },
    });
  });

  it("is null when the server remembers no run for the listing", async () => {
    vi.spyOn(api, "GET").mockResolvedValue(answer(404, undefined, { detail: "no AI run" }));

    await expect(findAiRun("take-a-hike")).resolves.toBeNull();
  });

  it("throws when the check itself fails", async () => {
    vi.spyOn(api, "GET").mockResolvedValue(answer(500, undefined, { detail: "boom" }));

    await expect(findAiRun("take-a-hike")).rejects.toBeInstanceOf(AiRunsApiError);
  });
});

describe("cancelAiRun", () => {
  it("deletes the run", async () => {
    const del = vi.spyOn(api, "DELETE").mockResolvedValue(answer(200, summary()));

    await expect(cancelAiRun("run-1")).resolves.toBe(true);
    expect(del).toHaveBeenCalledWith("/api/ai/runs/{run_id}", {
      params: { path: { run_id: "run-1" } },
    });
  });

  it("is false, not an error, when the run finished first", async () => {
    vi.spyOn(api, "DELETE").mockResolvedValue(answer(409, undefined, { detail: "finished" }));

    await expect(cancelAiRun("run-1")).resolves.toBe(false);
  });

  it("throws for an unknown run", async () => {
    vi.spyOn(api, "DELETE").mockResolvedValue(answer(404, undefined, { detail: "no AI run" }));

    await expect(cancelAiRun("run-1")).rejects.toBeInstanceOf(AiRunsApiError);
  });
});

describe("openAiRunStream", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  it("replays the run's events from the start, in order", async () => {
    const frames =
      'id: 1\nevent: step\ndata: {"type":"step","seq":1,"id":"brief","state":"active"}\n\n' +
      'id: 2\nevent: phase\ndata: {"type":"phase","seq":2,"phase":"done","message":null}\n\n';
    fetchMock.mockResolvedValue(new Response(frames, { status: 200 }));
    const events: unknown[] = [];
    let done = false;

    openAiRunStream("run 1", {
      onEvent: (event) => events.push(event),
      onDone: () => {
        done = true;
      },
    });

    await vi.waitFor(() => expect(done).toBe(true));
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/ai/runs/run%201/events");
    expect(fetchMock.mock.calls[0]?.[1]?.headers).toEqual({});
    expect(events.map((e) => (e as { seq: number }).seq)).toEqual([1, 2]);
  });
});
