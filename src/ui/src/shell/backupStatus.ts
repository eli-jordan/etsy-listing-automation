import { createContext, useContext } from "react";
import type { BackupStatus } from "../api/backup";
import { type BackupView, backupView } from "./backupAttention";

export const FAST_POLL_MS = 2000;
export const SLOW_POLL_MS = 30000;

export interface BackupStatusSource {
  view: BackupView;
  /** Lets a render say "2 hrs ago" without reading the clock. */
  readAt: number;
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
