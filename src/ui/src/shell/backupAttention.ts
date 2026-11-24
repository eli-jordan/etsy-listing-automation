import type { BackupStatus, BackupWarning, DestinationStatus } from "../api/backup";

/**
 * What a warning asks of the seller on Status and history: the banner
 * actions in workspace-backup interactions, *Warnings*.
 * - `connect`: the repository is missing; Create a new repository or
 *   Connect an existing repository.
 * - `repair`: a destination holds changed or unexpected files; Repair that
 *   copy.
 * - `retry`: every other warning (stale, failed, behind), answered together
 *   by one Try again.
 */
export type Attention =
  | { action: "connect"; warning: BackupWarning }
  | { action: "repair"; warning: BackupWarning; destination: DestinationStatus }
  | { action: "retry"; warnings: BackupWarning[] };

/** One destination's copy, as the diagram's pill draws it. */
export interface Copy {
  destination: DestinationStatus;
  /** The changed and unexpected files to check, while a `changed` warning
   * names this destination; otherwise 0. */
  toCheck: number;
}

interface Activity {
  /** A backup or a repair runs: Back up now and Try again wait for it. */
  running: boolean;
  /** A restore runs: every Restore… waits for it. */
  restoring: boolean;
}

/** Backups as set up, with what needs attention. */
export interface BackupsOn extends Activity {
  state: "on";
  status: BackupStatus;
  /** The warning the shell's banner and both nav marks show: the first of
   * `warnings`, or null when nothing needs attention. */
  banner: BackupWarning | null;
  /** Every warning that shows beyond the Backup page (all but `off`), in the
   * server's order. */
  warnings: BackupWarning[];
  /** The page's banners, in the order they show: a missing repository, each
   * changed copy in destination order, then one Try again for the rest. */
  attention: Attention[];
  /** Every destination, in settings order. */
  copies: Copy[];
}

/**
 * The shell's backup status as the app draws it. `loading` until the first
 * read answers; `error` when no read has answered yet and the last one
 * failed. Once a status is read, a failed read keeps it, so the view stays
 * `off` or `on`.
 */
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
  const retry = warnings.filter((w) => RETRYABLE.has(w.kind));
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

/** The warnings a backup run can clear, so Try again answers them. */
const RETRYABLE = new Set<BackupWarning["kind"]>(["stale", "failed", "behind"]);
