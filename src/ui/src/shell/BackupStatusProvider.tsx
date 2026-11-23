import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { type BackupStatus, getBackupStatus } from "../api/backup";
import { BackupStatusContext, FAST_POLL_MS, SLOW_POLL_MS } from "./backupStatus";

/**
 * The one poll of `GET /api/backup` (workspace-backup interactions, *What the
 * production implementation must finish*). The shell mounts it, so its banner
 * and dot, the Admin nav icon and the Backup page all read the same answer.
 * It polls faster while an operation or a restore runs, and not at all while the tab is
 * hidden; showing the tab again reads at once.
 */
export function BackupStatusProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<BackupStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [readAt, setReadAt] = useState(0);
  const [hidden, setHidden] = useState(() => document.visibilityState === "hidden");

  const refresh = useCallback(
    () =>
      getBackupStatus().then(
        (next) => {
          setStatus(next);
          setReadAt(Date.now());
          setError(null);
          return next;
        },
        (failure: unknown) => {
          setError(failure instanceof Error ? failure.message : "Could not read the backup status");
          return null;
        },
      ),
    [],
  );

  useEffect(() => {
    const onChange = () => setHidden(document.visibilityState === "hidden");
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);

  const running = Boolean(status?.running) || status?.restore?.outcome === "running";
  useEffect(() => {
    if (hidden) return;
    void refresh();
    const timer = setInterval(() => void refresh(), running ? FAST_POLL_MS : SLOW_POLL_MS);
    return () => clearInterval(timer);
  }, [hidden, running, refresh]);

  const value = useMemo(
    () => ({ status, error, readAt, refresh }),
    [status, error, readAt, refresh],
  );
  return <BackupStatusContext.Provider value={value}>{children}</BackupStatusContext.Provider>;
}
