import { api, withTuples } from "./client";
import type { CreateRunRequest, RunDetail, RunSummary } from "../types";

export class RunsApiError extends Error {}

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

export async function currentRun(listing: string): Promise<RunSummary | null> {
  const { data, error } = await api.GET("/api/runs", { params: { query: { listing } } });
  if (error || !data) throw new RunsApiError(`could not check runs for ${listing}`);
  return data[0] ?? null;
}

export async function currentWorkspaceRun(): Promise<RunSummary | null> {
  const { data, error } = await api.GET("/api/runs", {
    params: { query: { scope: "workspace" } },
  });
  if (error || !data) throw new RunsApiError("could not check workspace runs");
  return data[0] ?? null;
}

export async function currentBatchRun(batchId: string): Promise<RunSummary | null> {
  const { data, error } = await api.GET("/api/runs", {
    params: { query: { scope: "batch", batch: batchId } },
  });
  if (error || !data) throw new RunsApiError(`could not check deploy runs for ${batchId}`);
  return data[0] ?? null;
}

export function isReviewedScope(run: Pick<RunSummary, "scope">): boolean {
  return run.scope === "workspace" || run.scope === "batch";
}

export async function getRun(id: string): Promise<RunDetail> {
  const { data, error } = await api.GET("/api/runs/{run_id}", { params: { path: { run_id: id } } });
  if (error || !data) throw new RunsApiError(`could not load run ${id}`);
  return withTuples<RunDetail>(data);
}

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

export function runEventsUrl(id: string): string {
  return `/api/runs/${encodeURIComponent(id)}/events`;
}
