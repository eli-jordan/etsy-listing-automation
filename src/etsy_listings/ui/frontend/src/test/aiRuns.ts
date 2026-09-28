import { act } from "@testing-library/react";
import { type MockInstance, vi } from "vitest";
import * as aiRunsApi from "../api/aiRuns";
import * as marketApi from "../api/market";
import * as seoApi from "../api/seo";
import type { AiRunStreamOptions } from "../api/aiRuns";
import type { AiRun } from "../pages/editor/aiSeo/useAiRun";
import type {
  AiRunEvent,
  AiRunSummary,
  ListingProposal,
  MarketSnapshot,
  WorkflowStep,
} from "../types";

/**
 * A stand-in for the AI runs server, at `api/aiRuns.ts`'s seam: no run is
 * remembered, a start is accepted, a cancel succeeds, and every event
 * stream opened is kept so a test can push events down it. What a test
 * pushes is what the editor sees -- the same `step`/`brief`/`proposal`/
 * `phase` sequence `ui/airuns/runner.py` writes.
 *
 * It also stands in for the listing's cached proposal (A41) at `api/seo.ts`:
 * a `proposal` event pushed down a stream is cached first, exactly as the
 * runner writes the record before it announces it, and a resolution is
 * recorded on it -- or refused, as the server refuses one for a proposal
 * that has since been replaced.
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
  /** `GET …/market`: no snapshot unless a test gives one. */
  market: MockInstance<typeof marketApi.getMarketSnapshot>;
  /** The server's cached proposal: none unless a test or a `proposal` event
   * puts one there. */
  cached: { proposal: ListingProposal | null };
  /** `GET …/proposal`, answering {@link FakeAiRuns.cached}. */
  loadProposal: MockInstance<typeof seoApi.getListingProposal>;
  /** `PATCH …/proposal/resolution`, recorded on {@link FakeAiRuns.cached}. */
  resolveProposal: MockInstance<typeof seoApi.resolveListingProposal>;
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
  const market = vi.spyOn(marketApi, "getMarketSnapshot").mockResolvedValue(null);
  const cached: FakeAiRuns["cached"] = { proposal: null };
  const loadProposal = vi
    .spyOn(seoApi, "getListingProposal")
    .mockImplementation(async () => cached.proposal);
  const resolveProposal = vi
    .spyOn(seoApi, "resolveListingProposal")
    .mockImplementation(async (_name, { generated_at, ...sections }) => {
      const current = cached.proposal;
      if (current === null || current.generated_at !== generated_at) return null;
      const resolution = { ...current.resolution };
      for (const [key, value] of Object.entries(sections)) {
        if (value !== null && value !== undefined) {
          resolution[key as keyof typeof resolution] = value;
        }
      }
      cached.proposal = { ...current, resolution };
      return cached.proposal;
    });
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
        for (const event of events) {
          if (event.type === "proposal") cached.proposal = proposalOf(event);
          stream().options.onEvent(event);
        }
      }),
    end: () => act(() => stream().options.onDone?.()),
    find,
    start,
    cancel,
    market,
    cached,
    loadProposal,
    resolveProposal,
  };
}

function proposalOf(event: Extract<AiRunEvent, { type: "proposal" }>): ListingProposal {
  const { type, seq, ...proposal } = event;
  void type;
  void seq;
  return proposal;
}

/** A current proposal, every section still open. */
export function listingProposal(over: Partial<ListingProposal> = {}): ListingProposal {
  return {
    proposal: {
      titles: ["Title A", "Title B", "Title C"],
      tags: Array.from({ length: 20 }, (_, i) => `tag-${i}`),
      description_leads: ["Lead A", "Lead B", "Lead C"],
      rationale: [],
      warnings: [],
      observed_text: "",
    },
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
    generated_at: "2026-09-23T00:00:00Z",
    origin: "manual",
    resolution: { title: "pending", tags: "pending", lead: "pending" },
    stale: { is_stale: false, reasons: [] },
    ...over,
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

/** A `market` event: research finished and its snapshot was saved. */
export function marketEvent(snapshot: MarketSnapshot): AiRunEvent {
  return { type: "market", seq: ++seq, snapshot };
}

export function proposalEvent(proposal: ListingProposal = listingProposal()): AiRunEvent {
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
    autoNotice: false,
    dismissAutoNotice: vi.fn(),
    ...over,
  };
}
