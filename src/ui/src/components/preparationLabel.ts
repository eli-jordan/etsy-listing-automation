import type { Preparation } from "../api/preparation";
export function preparationLabel(value: Preparation | null): string {
  if (!value) return "Checking maps";
  if (value.active_job)
    return value.active_job.kind === "rebuild"
      ? "Updating maps"
      : value.active_job.phase === "queued"
        ? "Queued"
        : "Preparing";
  if (value.maps.can_render) return "Ready";
  if (value.latest_job?.phase === "failed") return "Failed";
  return value.maps.state === "out_of_date" ? "Out of date" : "Needs preparation";
}
