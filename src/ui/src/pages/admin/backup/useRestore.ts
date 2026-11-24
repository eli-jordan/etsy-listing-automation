import { useEffect, useState } from "react";
import {
  type BackupSnapshots,
  getBackupSnapshots,
  type RestoreStatus,
  startRestore,
  stopRestore,
} from "../../../api/backup";
import type { BackupsOn } from "../../../shell/backupAttention";

export type RestoreFlow = ReturnType<typeof useRestore>;

const failure = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback);

/**
 * The restore flow on Status and history (interactions, *Restore*). The
 * restore itself is the server's, read from the shell's status poll; this
 * holds only what the page shows of it. `shown` is whether its dialog
 * (progress, then Restored) is open. A dismissed restore's note stays away
 * until the next restore.
 */
export function useRestore(view: BackupsOn, refresh: () => Promise<unknown>) {
  const [picking, setPicking] = useState<{ snapshot: string | undefined } | null>(null);
  const [choices, setChoices] = useState<BackupSnapshots | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [shown, setShown] = useState(false);
  const [dismissed, setDismissed] = useState<string | null>(null);
  const latest = view.status.restore ?? null;
  const restore = latest && latest.started_at !== dismissed ? latest : null;

  useEffect(() => {
    if (!picking) return;
    let active = true;
    getBackupSnapshots().then(
      (found) => active && setChoices(found),
      (e: unknown) => active && setError(failure(e, "Could not read the backups")),
    );
    return () => {
      active = false;
    };
  }, [picking]);

  return {
    restore,
    shown,
    error,
    /** Only one restore runs at a time, so every Restore… waits for it. */
    busy: view.restoring,
    /** The dialog's choices, once read, while it is open. */
    picking: picking && choices ? { ...picking, choices } : null,
    /** Open the restore dialog on `snapshot`, or the newest. */
    begin(snapshot?: string) {
      setChoices(null);
      setError(null);
      setPicking({ snapshot });
    },
    cancel: () => setPicking(null),
    /** A refusal's message, or null once the restore has started. */
    async start(snapshot: string, target: string): Promise<string | null> {
      const answer = await startRestore(snapshot, target).catch((e: unknown) => ({
        refused: failure(e, "Could not reach the server"),
      }));
      if ("refused" in answer) return answer.refused;
      setDismissed(latest?.started_at ?? null); // the last restore's note gives way
      setPicking(null);
      setShown(true);
      await refresh();
      return null;
    },
    stop() {
      setShown(false);
      stopRestore().then(refresh, (e: unknown) =>
        setError(failure(e, "Could not stop the restore")),
      );
    },
    show: () => setShown(true),
    hide: () => setShown(false),
    dismiss(ended: RestoreStatus) {
      setShown(false);
      setDismissed(ended.started_at);
    },
  };
}
