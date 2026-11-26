import { api } from "./client";
import { type EventStreamHandle, type EventStreamOptions, openEventStream } from "./sse";
import type { AiRunEvent, AiRunSummary } from "../types";

export class AiRunsApiError extends Error {}

export const BATCH_PENDING_MESSAGE =
  "This listing is drafting in a batch. AI Mode is back once that is done.";

export const DEPLOYING_MESSAGE =
  "This listing is deploying. AI Mode is back once the deploy finishes.";

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
    if (refusal.reason === "batch_pending")
      return { kind: "refused", reason: BATCH_PENDING_MESSAGE };
    if (refusal.reason === "deploying") return { kind: "refused", reason: DEPLOYING_MESSAGE };
    if (refusal.reason) return { kind: "refused", reason: refusal.reason };
  }
  if (error || !data) throw new AiRunsApiError(`could not start an AI run for ${listing}`);
  return { kind: "started", run: data };
}

export async function findAiRun(listing: string): Promise<AiRunSummary | null> {
  const { data, error, response } = await api.GET("/api/ai/runs", {
    params: { query: { listing } },
  });
  if (response.status === 404) return null;
  if (error || !data) throw new AiRunsApiError(`could not check AI runs for ${listing}`);
  return data;
}

export async function cancelAiRun(id: string): Promise<boolean> {
  const { error, response } = await api.DELETE("/api/ai/runs/{run_id}", {
    params: { path: { run_id: id } },
  });
  if (response.status === 409) return false;
  if (error) throw new AiRunsApiError(`could not cancel AI run ${id}`);
  return true;
}

export type AiRunStreamOptions = Omit<EventStreamOptions<AiRunEvent>, "lastEventId">;

export function openAiRunStream(id: string, options: AiRunStreamOptions): EventStreamHandle {
  return openEventStream(`/api/ai/runs/${encodeURIComponent(id)}/events`, options);
}
