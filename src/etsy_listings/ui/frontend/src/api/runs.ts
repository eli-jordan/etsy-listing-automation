import { api } from "./client";
import type { CreateRunRequest, RunDetail, RunSummary } from "../types";

/**
 * The runs resource's REST surface (A33; docs/deploy-changes.md decision 7),
 * mirrored from `api/listings.ts`'s own shape: typed wrapper functions over
 * `openapi-fetch`, the only thing pages/components import. The sixth
 * endpoint, `GET /api/runs/{id}/events`, has no wrapper here -- it is
 * `text/event-stream`, not JSON, and `pages/deploy/runStream.ts` opens it
 * directly through `EventSource`, which needs a bare URL rather than a typed
 * client call.
 */

export class RunsApiError extends Error {}

/** `202` with the new run's summary, or `409` naming the run already holding
 * one of these listings -- the caller reattaches to that one instead of
 * retrying into the same refusal (`ui/api/runs.py`'s own docstring). */
export type CreateRunResult =
  { kind: "created"; run: RunSummary } | { kind: "conflict"; activeRun: string };

export async function createRun(body: CreateRunRequest): Promise<CreateRunResult> {
  const { data, error, response } = await api.POST("/api/runs", { body });
  if (response.status === 409) {
    const conflict = error as unknown as { active_run?: string } | undefined;
    if (conflict?.active_run) return { kind: "conflict", activeRun: conflict.active_run };
  }
  if (error || !data) throw new RunsApiError("could not start a run");
  return { kind: "created", run: data };
}

/** The current run holding `listing` -- active, or finished and not yet
 * superseded (decision 7's retention). Empty for a listing with no run this
 * server process remembers. */
export async function currentRun(listing: string): Promise<RunSummary | null> {
  const { data, error } = await api.GET("/api/runs", { params: { query: { listing } } });
  if (error || !data) throw new RunsApiError(`could not check runs for ${listing}`);
  return data[0] ?? null;
}

export async function getRun(id: string): Promise<RunDetail> {
  const { data, error } = await api.GET("/api/runs/{run_id}", { params: { path: { run_id: id } } });
  if (error || !data) throw new RunsApiError(`could not load run ${id}`);
  // `as unknown as RunDetail`: `events`' `ProgressEvent.swatches` tuple
  // (`[number, number, number]`) widens to `number[]` through openapi-fetch's
  // generic response extraction -- the same known gap `api/calibrator.ts`
  // already works around for `BoundingBox`, one level deeper here.
  return data as unknown as RunDetail;
}

/** Cancels a queued or planning/previewing run. Refuses (`409`) for an
 * apply, which the caller should already know not to try (decision 8: Back
 * leaves, it never cancels an apply) -- resolves `false` rather than
 * throwing, since a race with the run finishing on its own is not a defect. */
export async function cancelRun(id: string): Promise<boolean> {
  const { error, response } = await api.DELETE("/api/runs/{run_id}", {
    params: { path: { run_id: id } },
  });
  if (response.status === 409) return false;
  if (error) throw new RunsApiError(`could not cancel run ${id}`);
  return true;
}

export async function markRunSeen(id: string): Promise<void> {
  const { error } = await api.POST("/api/runs/{run_id}/seen", { params: { path: { run_id: id } } });
  if (error) throw new RunsApiError(`could not mark run ${id} seen`);
}

/** The SSE route's own URL -- not fetched through `openapi-fetch`, which has
 * no streaming mode; `runStream.ts` hands this straight to `EventSource`. */
export function runEventsUrl(id: string): string {
  return `/api/runs/${encodeURIComponent(id)}/events`;
}
