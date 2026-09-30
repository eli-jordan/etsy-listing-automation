import { api } from "./client";
import type { components } from "./schema";

/**
 * Staging and batches (batch plan PR 2, 4 and 5; ADR-0048, rename and delete hooks, ADR-0051): typed
 * wrappers over `/api/staging` and `/api/batches`, in
 * `api/listingTemplates.ts`'s shape.
 */

export type StagingDetail = components["schemas"]["StagingDetail"];
export type StagingRow = components["schemas"]["StagingRowDetail"];
export type StagingPatch = components["schemas"]["StagingPatch"];
export type StagingRefusal = components["schemas"]["StagingRefusal"];
export type BatchDetail = components["schemas"]["BatchDetail"];
export type BatchRow = components["schemas"]["BatchRowDetail"];
export type AiReadinessBlock = components["schemas"]["AiReadinessBlock"];
export type BatchIndexEntry = components["schemas"]["BatchIndexEntry"];
export type BatchStatus = BatchIndexEntry["status"];
export type ListingBatch = components["schemas"]["ListingBatch"];

export class BatchesApiError extends Error {}

/** An upload refused before staging (UI doc §4): what was wrong, and how to
 * fix it. Nothing was kept. */
export class StagingRefused extends BatchesApiError {
  constructor(readonly refusal: StagingRefusal) {
    super(refusal.message);
  }
}

function detailOf(error: unknown, fallback: string): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  return typeof detail === "string" ? detail : fallback;
}

/** Multipart, so a plain `fetch`: openapi-fetch would serialise the body as
 * JSON. */
export async function stageDesigns(listingTemplate: string, files: File[]): Promise<StagingDetail> {
  const form = new FormData();
  form.append("listing_template", listingTemplate);
  for (const file of files) form.append("files", file, file.name);
  const response = await fetch("/api/staging", { method: "POST", body: form });
  const body: unknown = await response.json().catch(() => undefined);
  if (response.ok) return body as StagingDetail;
  const detail = (body as { detail?: unknown } | undefined)?.detail;
  if (response.status === 422 && typeof detail === "object" && detail !== null) {
    throw new StagingRefused(detail as StagingRefusal);
  }
  throw new BatchesApiError(detailOf(body, "The designs could not be staged."));
}

export async function getStaging(id: string): Promise<StagingDetail> {
  const { data, error } = await api.GET("/api/staging/{session_id}", {
    params: { path: { session_id: id } },
  });
  if (error || !data) throw new BatchesApiError(detailOf(error, "This staging has gone."));
  return data;
}

export async function patchStaging(
  id: string,
  edit: Partial<StagingPatch>,
): Promise<StagingDetail> {
  const { data, error } = await api.PATCH("/api/staging/{session_id}", {
    params: { path: { session_id: id } },
    body: { names: edit.names ?? {}, remove: edit.remove ?? [], label: edit.label ?? null },
  });
  if (error || !data) throw new BatchesApiError(detailOf(error, "The change was not saved."));
  return data;
}

export async function cancelStaging(id: string): Promise<void> {
  const { response } = await api.DELETE("/api/staging/{session_id}", {
    params: { path: { session_id: id } },
  });
  if (response.status !== 204) throw new BatchesApiError("Staging could not be cancelled.");
}

/** Create the listings. Rejects with the server's sentence when the session
 * cannot be confirmed yet -- names to fix, or a shared ref that broke. */
export async function confirmStaging(id: string): Promise<BatchDetail> {
  const { data, error } = await api.POST("/api/staging/{session_id}/confirm", {
    params: { path: { session_id: id } },
  });
  if (error || !data) throw new BatchesApiError(detailOf(error, "The listings were not created."));
  return data;
}

export async function getBatch(id: string): Promise<BatchDetail> {
  const { data, error } = await api.GET("/api/batches/{batch_id}", {
    params: { path: { batch_id: id } },
  });
  if (error || !data) throw new BatchesApiError(detailOf(error, "No such batch."));
  return data;
}

/** Retry one row: its creation if that failed, else its AI. */
export async function retryBatchRow(id: string, row: string): Promise<BatchDetail> {
  const { data, error } = await api.POST("/api/batches/{batch_id}/rows/{row}/retry", {
    params: { path: { batch_id: id, row } },
  });
  if (error || !data) throw new BatchesApiError(detailOf(error, "Retry failed."));
  return data;
}

const CONTROLS = {
  cancel: "/api/batches/{batch_id}/cancel",
  resume: "/api/batches/{batch_id}/resume",
  retry: "/api/batches/{batch_id}/retry",
} as const;

/** The batch's queue controls: Cancel batch, Resume, and Retry N
 * failed. Each answers the batch as it is afterwards. */
export async function controlBatch(
  id: string,
  action: keyof typeof CONTROLS,
): Promise<BatchDetail> {
  const { data, error } = await api.POST(CONTROLS[action], {
    params: { path: { batch_id: id } },
  });
  if (error || !data) throw new BatchesApiError(detailOf(error, "The batch did not change."));
  return data;
}

export function stagingThumbnailUrl(id: string, row: string): string {
  return `/api/staging/${encodeURIComponent(id)}/rows/${encodeURIComponent(row)}/thumbnail`;
}

/** A never-created row's kept upload: it has no listing design to show. */
export function batchRowThumbnailUrl(id: string, row: string): string {
  return `/api/batches/${encodeURIComponent(id)}/rows/${encodeURIComponent(row)}/thumbnail`;
}

/** Recent batches (UI doc §2): every batch, and every unconfirmed staging
 * session, newest first, with a derived status. */
export async function listBatches(): Promise<BatchIndexEntry[]> {
  const { data, error } = await api.GET("/api/batches");
  if (error || !data) throw new BatchesApiError("Recent batches could not be loaded.");
  return data;
}

/** Rename the batch: its label only (UI doc §7). */
export async function renameBatch(id: string, label: string): Promise<BatchDetail> {
  const { data, error } = await api.PATCH("/api/batches/{batch_id}", {
    params: { path: { batch_id: id } },
    body: { label },
  });
  if (error || !data) throw new BatchesApiError(detailOf(error, "The batch was not renamed."));
  return data;
}

/** Delete batch record: its work is cancelled, and every listing, design,
 * brief and proposal stays (spec, *Cancellation and deletion*). */
export async function deleteBatch(id: string): Promise<void> {
  const { response } = await api.DELETE("/api/batches/{batch_id}", {
    params: { path: { batch_id: id } },
  });
  if (response.status !== 204) throw new BatchesApiError("The batch record was not deleted.");
}

/** Mark reviewed / Mark needs review (spec, *Review workflow*). */
export async function setReviewed(
  id: string,
  row: string,
  reviewed: boolean,
): Promise<BatchDetail> {
  const { data, error } = await api.PUT("/api/batches/{batch_id}/rows/{row}/reviewed", {
    params: { path: { batch_id: id, row } },
    body: { reviewed },
  });
  if (error || !data) throw new BatchesApiError(detailOf(error, "Reviewed was not changed."));
  return data;
}

/** The batch that made a listing, or `null` (UI doc §8). */
export async function getListingBatch(name: string): Promise<ListingBatch | null> {
  const { data, error } = await api.GET("/api/listings/{name}/batch", {
    params: { path: { name } },
  });
  if (error) throw new BatchesApiError(detailOf(error, "The listing's batch could not be read."));
  return data ?? null;
}
