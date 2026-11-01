import type { Preparation } from "../api/preparation";
import { marigoldMapsReady } from "./preparationLabel";

export function activePreparationStep(step: string): number {
  const normalized = step.toLowerCase();
  if (normalized.includes("normal")) return 0;
  if (normalized.includes("lighting")) return 1;
  if (normalized.includes("depth")) return 2;
  if (normalized.includes("build") || normalized.includes("bake")) return 3;
  return -1;
}

export function preparationAction(preparation: Preparation | null) {
  if (preparation?.latest_job?.phase === "failed") return "retry";
  if (preparation?.maps.reason === "photo_changed" || marigoldMapsReady(preparation?.maps))
    return "prepare_again";
  return "prepare";
}

export function prepareButtonLabel(
  action: ReturnType<typeof preparationAction>,
  recovery: boolean,
): string {
  if (action === "retry") return "Retry preparation";
  if (recovery) return "Reset masks and prepare";
  return action === "prepare_again" ? "Prepare again" : "Prepare template";
}

export function mapStatusClass(label: string): string {
  if (label === "Ready") return " mg-status--ready";
  return label === "Failed" ? " mg-status--failed" : "";
}
