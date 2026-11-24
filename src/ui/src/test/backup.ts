import type { BackupStatus, BackupWarning, DestinationStatus } from "../api/backup";

/**
 * `GET /api/backup` answers, shaped as `core/application/backup_overview.py`
 * builds them. Each builder takes overrides for what a test cares about.
 */

export const BACKUP_REPOSITORY = "D:/backups/studio";
export const BACKUP_ICLOUD = "C:/Users/me/iCloudDrive/studio-backups";

const HOUR = 3_600_000;
/** An ISO time `offsetHours` from now. */
export const hoursFromNow = (offsetHours: number) =>
  new Date(Date.now() + offsetHours * HOUR).toISOString();

/** Backups switched off: the one warning the server sends, kept off the banner. */
export function backupsOff(over: Partial<BackupStatus> = {}): BackupStatus {
  return {
    enabled: false,
    destinations: [],
    warnings: [{ kind: "off", message: "Backups are off.", banner: false }],
    ...over,
  };
}

/** A healthy set-up backup: last run two hours ago, one iCloud destination. */
export function backupsOn(over: Partial<BackupStatus> = {}): BackupStatus {
  return {
    enabled: true,
    interval_hours: 12,
    last_success: hoursFromNow(-2),
    next_due: hoursFromNow(10),
    repository: { path: BACKUP_REPOSITORY, missing: false, snapshots: 5, password_stored: true },
    destinations: [backupDestination()],
    warnings: [],
    ...over,
  };
}

export function backupDestination(over: Partial<DestinationStatus> = {}): DestinationStatus {
  return {
    path: BACKUP_ICLOUD,
    last_copy: hoursFromNow(-2),
    behind: false,
    changed: [],
    unexpected: [],
    ...over,
  };
}

/** A warning as the server words it, shown beyond the Backup page. */
export function backupWarning(
  kind: BackupWarning["kind"],
  over: Partial<BackupWarning> = {},
): BackupWarning {
  return { kind, message: MESSAGES[kind], banner: kind !== "off", ...over };
}

const MESSAGES: Record<BackupWarning["kind"], string> = {
  off: "Backups are off.",
  repository_missing: `Backup repository not found at ${BACKUP_REPOSITORY}. Backups have stopped.`,
  stale: "The last backup is more than a day old.",
  failed: "The last backup failed: disk full",
  behind: `${BACKUP_ICLOUD} is more than a day behind the backups.`,
  changed: `Something else changed files in ${BACKUP_ICLOUD}.`,
};

/** The repository folder is gone: the server sends only that warning. */
export function backupsMissing(passwordStored = true): BackupStatus {
  return backupsOn({
    last_success: null,
    next_due: null,
    repository: {
      path: BACKUP_REPOSITORY,
      missing: true,
      snapshots: 0,
      password_stored: passwordStored,
    },
    destinations: [],
    warnings: [backupWarning("repository_missing")],
  });
}
