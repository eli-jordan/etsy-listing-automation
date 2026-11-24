import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { type BackupStatus, getBackupStatus } from "../api/backup";
import { backupView } from "./backupAttention";
import { BackupStatusContext, FAST_POLL_MS, SLOW_POLL_MS } from "./backupStatus";

/**
 * The one poll of `GET /api/backup` (workspace-backup interactions, *What the
 * production implementation must finish*). The shell mounts it, so its banner
 * and dot, the Admin nav icon and the Backup page all read the same answer,
 * as one `BackupView` (`backupAttention.ts`).
 * It polls faster while an operation or a restore runs, and not at all while the tab is
 * hidden; showing the tab again reads at once.
 */
export function BackupStatusProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<BackupStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [readAt, setReadAt] = useState(0);
  const [hidden, setHidden] = useState(() => document.visibilityState === "hidden");
  const requested = useRef(0);
  const applied = useRef(0);
  const latest = useRef<BackupStatus | null>(null);

  const refresh = useCallback(() => {
    const request = ++requested.current;
    function apply(update: () => void) {
      if (request < applied.current) return;
      applied.current = request;
      update();
    }
    return getBackupStatus().then(
      (next) => {
        apply(() => {
          latest.current = next;
          setStatus(next);
          setReadAt(Date.now());
          setError(null);
        });
        return latest.current;
      },
      (failure: unknown) => {
        apply(() => {
          setError(failure instanceof Error ? failure.message : "Could not read the backup status");
        });
        return latest.current;
      },
    );
  }, []);

  useEffect(() => {
    const onChange = () => setHidden(document.visibilityState === "hidden");
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);

  const view = useMemo(() => backupView(status, error), [status, error]);
  const fast = view.running || view.restoring;
  useEffect(() => {
    if (hidden) return;
    void refresh();
    const timer = setInterval(() => void refresh(), fast ? FAST_POLL_MS : SLOW_POLL_MS);
    return () => clearInterval(timer);
  }, [hidden, fast, refresh]);

  const value = useMemo(() => ({ view, readAt, refresh }), [view, readAt, refresh]);
  return <BackupStatusContext.Provider value={value}>{children}</BackupStatusContext.Provider>;
}
