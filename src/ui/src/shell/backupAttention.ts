import type { BackupStatus, BackupWarning, DestinationStatus } from "../api/backup";

export type Attention =
  | { action: "connect"; warning: BackupWarning }
  | { action: "repair"; warning: BackupWarning; destination: DestinationStatus }
  | { action: "retry"; warnings: BackupWarning[] };

export interface Copy {
  destination: DestinationStatus;
  toCheck: number;
}

interface Activity {
  running: boolean;
  restoring: boolean;
}

export interface BackupsOn extends Activity {
  state: "on";
  status: BackupStatus;
  banner: BackupWarning | null;
  warnings: BackupWarning[];
  attention: Attention[];
  copies: Copy[];
}

export type BackupView =
  | (Activity & { state: "loading"; banner: null })
  | (Activity & { state: "error"; error: string; banner: null })
  | (Activity & { state: "off"; status: BackupStatus; banner: null })
  | BackupsOn;

const IDLE: Activity = { running: false, restoring: false };

export function backupView(status: BackupStatus | null, error: string | null): BackupView {
  if (!status)
    return error
      ? { ...IDLE, state: "error", error, banner: null }
      : { ...IDLE, state: "loading", banner: null };
  const activity: Activity = {
    running: Boolean(status.running),
    restoring: status.restore?.outcome === "running",
  };
  if (!status.enabled) return { ...activity, state: "off", status, banner: null };

  const warnings = status.warnings.filter((warning) => warning.banner);
  const changed = (d: DestinationStatus) =>
    warnings.find((w) => w.kind === "changed" && w.destination === d.path);
  const attention: Attention[] = [];
  const missing = warnings.find((w) => w.kind === "repository_missing");
  if (missing) attention.push({ action: "connect", warning: missing });
  for (const destination of status.destinations) {
    const warning = changed(destination);
    if (warning) attention.push({ action: "repair", warning, destination });
  }
  const retry = warnings.filter((w) => CLEARED_BY_A_BACKUP_RUN.has(w.kind));
  if (retry.length) attention.push({ action: "retry", warnings: retry });

  return {
    ...activity,
    state: "on",
    status,
    banner: warnings[0] ?? null,
    warnings,
    attention,
    copies: status.destinations.map((destination) => ({
      destination,
      toCheck: changed(destination)
        ? destination.changed.length + destination.unexpected.length
        : 0,
    })),
  };
}

const CLEARED_BY_A_BACKUP_RUN = new Set<BackupWarning["kind"]>(["stale", "failed", "behind"]);
