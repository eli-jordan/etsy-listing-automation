import { useEffect, useState } from "react";
import {
  type BackupSnapshots,
  getBackupSnapshots,
  type RestoreStatus,
  startRestore,
  stopRestore,
} from "../../../api/backup";
import type { BackupsOn } from "../../../shell/backupAttention";
import type { SubmitFailure } from "./backupText";

export type RestoreFlow = ReturnType<typeof useRestore>;

const failure = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback);

/** The restore flow on Status and history (interactions, *Restore*). */
export function useRestore(view: BackupsOn, refresh: () => Promise<unknown>) {
  const [picking, setPicking] = useState<{ snapshot: string | undefined } | null>(null);
  const [choices, setChoices] = useState<BackupSnapshots | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dismissedStartedAt, setDismissedStartedAt] = useState<string | null>(null);
  const latest = view.status.restore ?? null;
  const restore = latest && latest.started_at !== dismissedStartedAt ? latest : null;

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
    dialogOpen,
    error,
    busy: view.restoring,
    picking: picking && choices ? { ...picking, choices } : null,
    begin(snapshot?: string) {
      setChoices(null);
      setError(null);
      setPicking({ snapshot });
    },
    cancel: () => setPicking(null),
    async start(snapshot: string, target: string): Promise<SubmitFailure> {
      const answer = await startRestore(snapshot, target).catch(
        (e: unknown) =>
          ({ kind: "refused", message: failure(e, "Could not reach the server") }) as const,
      );
      if (answer.kind !== "started") return answer.message;
      setDismissedStartedAt(latest?.started_at ?? null); // the last restore's note gives way
      setPicking(null);
      setDialogOpen(true);
      await refresh();
      return null;
    },
    stop() {
      setDialogOpen(false);
      stopRestore().then(refresh, (e: unknown) =>
        setError(failure(e, "Could not stop the restore")),
      );
    },
    show: () => setDialogOpen(true),
    hide: () => setDialogOpen(false),
    dismiss(ended: RestoreStatus) {
      setDialogOpen(false);
      setDismissedStartedAt(ended.started_at);
    },
  };
}
