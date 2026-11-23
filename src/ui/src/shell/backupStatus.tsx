import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { type BackupStatus, type BackupWarning, getBackupStatus } from "../api/backup";

/** While a backup or repair runs, so the running line moves. */
export const FAST_POLL_MS = 2000;
/** Otherwise: warnings appear and clear within half a minute. */
export const SLOW_POLL_MS = 30000;

export interface BackupStatusSource {
  /** Null until the first read answers, and after a read fails. */
  status: BackupStatus | null;
  error: string | null;
  /** Read now, for an action that changed it; resolves with the new status. */
  refresh: () => Promise<BackupStatus | null>;
}

const Context = createContext<BackupStatusSource>({
  status: null,
  error: null,
  refresh: () => Promise.resolve(null),
});

/** The warnings that show beyond the Backup page: all but `off`. */
export function bannerWarnings(status: BackupStatus | null): BackupWarning[] {
  return (status?.warnings ?? []).filter((warning) => warning.banner);
}

/**
 * The one poll of `GET /api/backup` (workspace-backup interactions, *What the
 * production implementation must finish*). The shell mounts it, so its banner
 * and dot, the Admin nav icon and the Backup page all read the same answer.
 * It polls faster while an operation runs, and not at all while the tab is
 * hidden; showing the tab again reads at once.
 */
export function BackupStatusProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<BackupStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hidden, setHidden] = useState(() => document.visibilityState === "hidden");

  const refresh = useCallback(
    () =>
      getBackupStatus().then(
        (next) => {
          setStatus(next);
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

  const running = Boolean(status?.running);
  useEffect(() => {
    if (hidden) return;
    void refresh();
    const timer = setInterval(() => void refresh(), running ? FAST_POLL_MS : SLOW_POLL_MS);
    return () => clearInterval(timer);
  }, [hidden, running, refresh]);

  const value = useMemo(() => ({ status, error, refresh }), [status, error, refresh]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useBackupStatus(): BackupStatusSource {
  return useContext(Context);
}
