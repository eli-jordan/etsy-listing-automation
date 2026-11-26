import type { Preparation } from "../api/preparation";
export function marigoldMapsReady(maps: Preparation["maps"] | null | undefined): boolean {
  return maps?.state === "ready" && maps.can_render;
}
function activeJobLabel(job: NonNullable<Preparation["active_job"]>): string {
  if (job.waiting_for_backup) return "Waiting for backup";
  if (job.kind === "rebuild") return "Rebuilding maps";
  return job.phase === "queued" ? "Queued" : "Preparing";
}
export function preparationLabel(value: Preparation | null): string {
  if (!value) return "Checking maps";
  if (value.active_job) return activeJobLabel(value.active_job);
  if (marigoldMapsReady(value.maps)) return "Ready";
  if (value.latest_job?.phase === "failed") return "Failed";
  return value.maps.state === "out_of_date" ? "Out of date" : "Needs preparation";
}
