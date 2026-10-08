import type { components } from "./schema";
import { api } from "./client";
import { openEventStream, type EventStreamOptions } from "./sse";
export type Preparation = components["schemas"]["PreparationResponse"];
export type PreparationJob = components["schemas"]["PreparationJobResponse"];
export type MaskEdit = components["schemas"]["MaskEdit"];
export type MaskOperation = MaskEdit["operations"][number];
export type Runtime = components["schemas"]["MarigoldRuntimeResponse"];
export async function getPreparation(name: string, signal?: AbortSignal): Promise<Preparation> {
  const { data, error } = await api.GET("/api/templates/{name}/preparation", {
    params: { path: { name } },
    ...(signal ? { signal } : {}),
  });
  if (error || !data) throw new Error("Could not read template map status. Try again.");
  return data;
}
export async function getRuntime(): Promise<Runtime> {
  const { data, error } = await api.GET("/api/marigold/runtime");
  if (error || !data) throw new Error("Could not check the Marigold runtime.");
  return data;
}
export async function listPreparationJobs(): Promise<PreparationJob[]> {
  const { data, error } = await api.GET("/api/preparation/jobs");
  if (error || !data) throw new Error("Could not read the preparation queue.");
  return data;
}
export async function prepareTemplate(
  body: components["schemas"]["CreatePreparationRequest"],
): Promise<PreparationJob> {
  const { data, error } = await api.POST("/api/preparation/jobs", { body });
  if (error || !data)
    throw new Error(
      "Preparation could not start. Check runtime availability and save the template again.",
    );
  return data;
}
export async function cancelPreparation(identity: string): Promise<PreparationJob> {
  const { data, error } = await api.DELETE("/api/preparation/jobs/{identity}", {
    params: { path: { identity } },
  });
  if (error || !data) throw new Error("Could not cancel preparation. Try again.");
  return data;
}
export type PreparationEvent =
  | components["schemas"]["Event"]
  | PreparationJob
  | components["schemas"]["PreparationResyncResponse"];
export function followPreparation(id: string, options: EventStreamOptions<PreparationEvent>) {
  return openEventStream(`/api/preparation/jobs/${encodeURIComponent(id)}/events`, options);
}
export function maskUrl(
  name: string,
  placementId: string | null,
  automatic = false,
  revision = "",
) {
  const placement = placementId === null ? "" : `/placements/${encodeURIComponent(placementId)}`;
  return `/api/templates/${encodeURIComponent(name)}${placement}/mask?source=${automatic ? "automatic" : "edited"}&revision=${encodeURIComponent(revision)}`;
}
export type MaskHistory = components["schemas"]["MaskHistoryResponse"];
export async function getMaskHistory(
  name: string,
  placementId: string | null,
): Promise<MaskHistory> {
  const result =
    placementId === null
      ? await api.GET("/api/templates/{name}/mask-history", { params: { path: { name } } })
      : await api.GET("/api/templates/{name}/placements/{placement_id}/mask-history", {
          params: { path: { name, placement_id: placementId } },
        });
  if (result.error || !result.data)
    throw new Error("Could not read brush history. Saved masks remain available.");
  // openapi-fetch widens nested coordinate tuples. The response contract validates pairs.
  return result.data as unknown as MaskHistory;
}
