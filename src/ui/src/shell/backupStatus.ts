import { createContext, useContext } from "react";
import type { BackupStatus } from "../api/backup";
import { type BackupView, backupView } from "./backupAttention";

/** While a backup, repair or restore runs, so the running line moves. */
export const FAST_POLL_MS = 2000;
/** Otherwise: warnings appear and clear within half a minute. */
export const SLOW_POLL_MS = 30000;

export interface BackupStatusSource {
  view: BackupView;
  /** When the view's status was read, for "2 hrs ago" without reading the clock in render. */
  readAt: number;
  /** Read now, for an action that changed it. Resolves with the latest status
   * read once this read is answered: the newer one when a later poll answered
   * first, and the one kept when this read failed. */
  refresh: () => Promise<BackupStatus | null>;
}

export const BackupStatusContext = createContext<BackupStatusSource>({
  view: backupView(null, null),
  readAt: 0,
  refresh: () => Promise.resolve(null),
});

export function useBackupStatus(): BackupStatusSource {
  return useContext(BackupStatusContext);
}
