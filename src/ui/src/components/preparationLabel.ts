import type { Preparation } from "../api/preparation";
export function marigoldMapsReady(maps: Preparation["maps"] | null | undefined): boolean {
  return maps?.state === "ready" && maps.can_render;
}
export function preparationLabel(value: Preparation | null): string {
  if (!value) return "Checking maps";
  if (value.active_job) {
    if (value.active_job.kind === "rebuild") return "Rebuilding maps";
    return value.active_job.phase === "queued" ? "Queued" : "Preparing";
  }
  if (marigoldMapsReady(value.maps)) return "Ready";
  if (value.latest_job?.phase === "failed") return "Failed";
  return value.maps.state === "out_of_date" ? "Out of date" : "Needs preparation";
}
