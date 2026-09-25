import { act } from "@testing-library/react";
import { type MockInstance, vi } from "vitest";
import * as aiRunsApi from "../api/aiRuns";
import type { AiRunStreamOptions } from "../api/aiRuns";
import type { AiRun } from "../pages/editor/aiSeo/useAiRun";
import type { AiRunEvent, AiRunSummary, SeoProposalResponse, WorkflowStep } from "../types";

/**
 * A stand-in for the AI runs server, at `api/aiRuns.ts`'s seam: no run is
 * remembered, a start is accepted, a cancel succeeds, and every event
 * stream opened is kept so a test can push events down it. What a test
 * pushes is what the editor sees -- the same `step`/`brief`/`proposal`/
 * `phase` sequence `ui/airuns/runner.py` writes.
 */

export function aiRunSummary(over: Partial<AiRunSummary> = {}): AiRunSummary {
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
    created_at: new Date().toISOString(),
    finished_at: null,
    ...over,
  };
}

export interface FakeStream {
  runId: string;
  options: AiRunStreamOptions;
  closed: boolean;
}

export interface FakeAiRuns {
  streams: FakeStream[];
  /** The most recently opened stream. */
  stream: () => FakeStream;
  /** Pushes events down the most recent stream, inside `act`. */
  emit: (...events: AiRunEvent[]) => void;
  /** Ends the most recent stream, as the server does after `phase`. */
  end: () => void;
  find: MockInstance<typeof aiRunsApi.findAiRun>;
  start: MockInstance<typeof aiRunsApi.startAiRun>;
  cancel: MockInstance<typeof aiRunsApi.cancelAiRun>;
}

export function fakeAiRuns(): FakeAiRuns {
  const streams: FakeStream[] = [];
  const find = vi.spyOn(aiRunsApi, "findAiRun").mockResolvedValue(null);
  const start = vi
    .spyOn(aiRunsApi, "startAiRun")
    .mockImplementation(async (listing, { draftBrief }) => ({
      kind: "started",
      run: aiRunSummary({
        listing,
        draft_brief: draftBrief,
        steps: [
          draftBrief
            ? { id: "brief", state: "pending", detail: null }
            : { id: "brief", state: "skipped", detail: "You wrote the brief, so it was kept" },
          { id: "market", state: "pending", detail: null },
          { id: "seo", state: "pending", detail: null },
        ],
      }),
    }));
  const cancel = vi.spyOn(aiRunsApi, "cancelAiRun").mockResolvedValue(true);
  vi.spyOn(aiRunsApi, "openAiRunStream").mockImplementation((runId, options) => {
    const stream: FakeStream = { runId, options, closed: false };
    streams.push(stream);
    return {
      close: () => {
        stream.closed = true;
      },
    };
  });

  function stream(): FakeStream {
    const latest = streams.at(-1);
    if (latest === undefined) throw new Error("no AI run stream was opened");
    return latest;
  }

  return {
    streams,
    stream,
    emit: (...events) =>
      act(() => {
        for (const event of events) stream().options.onEvent(event);
      }),
    end: () => act(() => stream().options.onDone?.()),
    find,
    start,
    cancel,
  };
}

let seq = 0;

/** A `step` event, numbered after the previous event any builder made. */
export function stepEvent(
  id: WorkflowStep["id"],
  state: WorkflowStep["state"],
  detail: string | null = null,
): AiRunEvent {
  return { type: "step", seq: ++seq, id, state, detail };
}

export function briefEvent(text: string, written = true): AiRunEvent {
  return { type: "brief", seq: ++seq, text, written };
}

export function queriesEvent(queries: string[]): AiRunEvent {
  return { type: "queries", seq: ++seq, queries };
}

export function proposalEvent(proposal: SeoProposalResponse): AiRunEvent {
  return { ...proposal, type: "proposal", seq: ++seq };
}

export function phaseEvent(
  phase: "done" | "failed" | "cancelled",
  message: string | null = null,
): AiRunEvent {
  return { type: "phase", seq: ++seq, phase, message };
}

/** An idle `useAiRun` result, for a component test that stubs `AiSeoMode`. */
export function aiRunStub(over: Partial<AiRun> = {}): AiRun {
  return {
    phase: "idle",
    busy: false,
    steps: [],
    queries: null,
    market: null,
    proposal: null,
    message: null,
    startedAt: null,
    start: vi.fn(),
    cancel: vi.fn(),
    arm: vi.fn(),
    ...over,
  };
}
