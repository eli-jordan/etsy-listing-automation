import { createContext, useContext } from "react";
import type { BackupStatus, BackupWarning } from "../api/backup";

/** While a backup or repair runs, so the running line moves. */
export const FAST_POLL_MS = 2000;
/** Otherwise: warnings appear and clear within half a minute. */
export const SLOW_POLL_MS = 30000;

export interface BackupStatusSource {
  /** Null until the first read answers, and after a read fails. */
  status: BackupStatus | null;
  error: string | null;
  /** When `status` was read, for "2 hrs ago" without reading the clock in render. */
  readAt: number;
  /** Read now, for an action that changed it; resolves with the new status. */
  refresh: () => Promise<BackupStatus | null>;
}

export const BackupStatusContext = createContext<BackupStatusSource>({
  status: null,
  error: null,
  readAt: 0,
  refresh: () => Promise.resolve(null),
});

/** The warnings that show beyond the Backup page: all but `off`. */
export function bannerWarnings(status: BackupStatus | null): BackupWarning[] {
  return (status?.warnings ?? []).filter((warning) => warning.banner);
}

/** The shell's one backup status (`BackupStatusProvider`). */
export function useBackupStatus(): BackupStatusSource {
  return useContext(BackupStatusContext);
}
