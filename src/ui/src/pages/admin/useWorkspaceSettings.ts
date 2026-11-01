import { useCallback, useEffect, useState } from "react";
import {
  getSettings,
  saveSettings,
  type SettingsChanges,
  type WorkspaceSettings,
} from "../../api/workspaceSettings";
import { useSaveQueue } from "./useSaveQueue";

const send = (revision: string, changes: SettingsChanges) =>
  saveSettings(revision, changes).then((outcome) =>
    outcome.kind === "saved" ? { ...outcome, revision: outcome.settings.revision } : outcome,
  );

/** Which change answers a field error: the server names `settings.yaml`
 * keys, the page sends its own change names. */
const clears = (key: string, changes: SettingsChanges) =>
  (key.startsWith("batch_ai") && "concurrency" in changes) ||
  (key.startsWith("ai.providers") && "providers" in changes) ||
  (key === "ai.step_limit_minutes" && "step_limit_minutes" in changes) ||
  (key === "ai.run_limit_minutes" && "run_limit_minutes" in changes) ||
  (key.startsWith("market_seo") && "weights" in changes);

/** settings.yaml's revision and save queue (`useSaveQueue`), independent of
 * Shop. Responses advance the revision without replacing newer local edits:
 * controls drop theirs only when `loadedVersion` changes, on a (re)load. A
 * conflict stops queued edits until an explicit reload (ADR-0055).
 */
export function useWorkspaceSettings() {
  const [settings, setSettings] = useState<WorkspaceSettings | null>(null);
  const [loadedVersion, setLoadedVersion] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const queue = useSaveQueue({ send, clears, fallback: "Could not save settings.yaml" });
  const { reset, afterSaves, save: enqueue, retry: resend } = queue;

  const adopt = useCallback(
    (loaded: WorkspaceSettings) => {
      reset(loaded.revision);
      setSettings(loaded);
      setLoadedVersion((version) => version + 1);
      setLoadError(null);
    },
    [reset],
  );
  const refuse = useCallback((error: unknown) => {
    setSettings(null);
    setLoadError(error instanceof Error ? error.message : "Could not read settings.yaml");
  }, []);
  const reload = useCallback(
    () => afterSaves(() => getSettings()).then(adopt, refuse),
    [afterSaves, adopt, refuse],
  );
  useEffect(() => {
    let active = true;
    getSettings().then(
      (loaded) => {
        if (active) adopt(loaded);
      },
      (error: unknown) => {
        if (active) refuse(error);
      },
    );
    return () => {
      active = false;
    };
  }, [adopt, refuse]);

  // The status line reports failures; a caller has nothing to await.
  const save = useCallback(
    (changes: SettingsChanges) => void enqueue(changes).catch(() => undefined),
    [enqueue],
  );
  const retry = useCallback(() => void resend().catch(() => undefined), [resend]);

  return {
    settings,
    loadedVersion,
    status: queue.status,
    fieldErrors: queue.fieldErrors as Record<string, string>,
    loadError,
    reload,
    save,
    retry,
    locked: queue.locked,
  };
}
