import { api } from "./client";
import { type EventStreamHandle, type EventStreamOptions, openEventStream } from "./sse";
import type { AiRunEvent, AiRunSummary } from "../types";

/**
 * The AI runs resource (market-seo.md, *AI runs*; the implementation plan's
 * Run contract): typed wrappers over `/api/ai/runs`, the only thing the
 * editor imports to start, find, follow and cancel one. Shaped like
 * `api/runs.ts`, the plan/apply runs' client, because the resource is shaped
 * like that one.
 */

export class AiRunsApiError extends Error {}

/** What `POST /api/ai/runs` can answer besides a failure: the run it
 * started, the run already active for the listing (reattach to it rather
 * than retry into the same refusal), or the readiness rule that refused it. */
export type StartAiRunResult =
  | { kind: "started"; run: AiRunSummary }
  | { kind: "active"; runId: string }
  | { kind: "refused"; reason: string };

export async function startAiRun(
  listing: string,
  { draftBrief }: { draftBrief: boolean },
): Promise<StartAiRunResult> {
  const { data, error, response } = await api.POST("/api/ai/runs", {
    body: { listing, draft_brief: draftBrief },
  });
  if (response.status === 409) {
    const refusal = (error ?? {}) as { active_run?: string | null; reason?: string | null };
    if (refusal.active_run) return { kind: "active", runId: refusal.active_run };
    if (refusal.reason) return { kind: "refused", reason: refusal.reason };
  }
  if (error || !data) throw new AiRunsApiError(`could not start an AI run for ${listing}`);
  return { kind: "started", run: data };
}

/** The listing's running or most recent run -- what the editor reattaches
 * to on mount -- or `null` when this server process remembers none. */
export async function findAiRun(listing: string): Promise<AiRunSummary | null> {
  const { data, error, response } = await api.GET("/api/ai/runs", {
    params: { query: { listing } },
  });
  if (response.status === 404) return null;
  if (error || !data) throw new AiRunsApiError(`could not check AI runs for ${listing}`);
  return data;
}

/** Cancels a running run: its provider subprocess tree is killed, and a
 * brief or snapshot already written stays. `false` when the run finished
 * first -- a race with the run ending on its own is not a defect. */
export async function cancelAiRun(id: string): Promise<boolean> {
  const { error, response } = await api.DELETE("/api/ai/runs/{run_id}", {
    params: { path: { run_id: id } },
  });
  if (response.status === 409) return false;
  if (error) throw new AiRunsApiError(`could not cancel AI run ${id}`);
  return true;
}

export type AiRunStreamOptions = Omit<EventStreamOptions<AiRunEvent>, "lastEventId">;

/** Every event the run has produced, then each new one until its last
 * (`phase`). Always from the start: the editor rebuilds its whole view of a
 * run from the events, so it never has a position to resume from. */
export function openAiRunStream(id: string, options: AiRunStreamOptions): EventStreamHandle {
  return openEventStream(`/api/ai/runs/${encodeURIComponent(id)}/events`, options);
}
