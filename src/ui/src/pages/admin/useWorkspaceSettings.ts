import { useCallback, useState } from "react";
import {
  type BackupSetUp,
  type ConnectRepository,
  connectRepository,
  createRepository,
  type NewRepository,
  type SetUpOutcome,
  setUpBackup,
} from "../../api/backup";
import {
  getSettings,
  saveSettings,
  type SettingsChanges,
  type WorkspaceSettings,
} from "../../api/workspaceSettings";
import { useQueuedFile } from "./useQueuedFile";
import { useSaveQueue } from "./useSaveQueue";

// Resolved at call time, so a reload reads whatever `getSettings` is then.
const loadSettings = () => getSettings();
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
  (key.startsWith("market_seo") && "weights" in changes) ||
  (key.startsWith("template_positions") && "template_positions" in changes) ||
  (key.startsWith("backup") && Object.keys(changes).some((change) => change.startsWith("backup")));

/** A missing-repository action's answers, without the revision. */
export type RepositoryAction =
  | { kind: "create"; body: Omit<NewRepository, "revision"> }
  | { kind: "connect"; body: Omit<ConnectRepository, "revision"> };

/** settings.yaml's revision and save queue (`useSaveQueue`), independent of
 * Shop. Responses advance the revision without replacing newer local edits:
 * controls drop theirs only when `loadedVersion` changes, on a (re)load. A
 * conflict stops queued edits until an explicit reload (ADR-0055).
 */
export function useWorkspaceSettings() {
  const [settings, setSettings] = useState<WorkspaceSettings | null>(null);
  const queue = useSaveQueue({ send, clears, fallback: "Could not save settings.yaml" });
  const { save: enqueue, retry: resend } = queue;
  const clear = useCallback(() => setSettings(null), []);
  const { loadedVersion, loadError, reload } = useQueuedFile({
    load: loadSettings,
    queue,
    onLoaded: setSettings,
    onRefused: clear,
    fallback: "Could not read settings.yaml",
  });

  // The status line reports failures; a caller has nothing to await.
  const save = useCallback(
    (changes: SettingsChanges) => void enqueue(changes).catch(() => undefined),
    [enqueue],
  );
  const retry = useCallback(() => void resend().catch(() => undefined), [resend]);
  // A confirmed save (template limits) reports its own failure and retries
  // only through its own button, like the currency dialog (`retain: false`).
  const confirmSave = useCallback(
    (changes: SettingsChanges) => enqueue(changes, { retain: false }),
    [enqueue],
  );

  // Backup's set-up and the missing-repository actions write settings.yaml
  // outside the queue: after the queued saves, naming their revision, then
  // reloading the file they changed.
  const { afterSaves, currentRevision } = queue;
  const outsideQueue = useCallback(
    (send: (revision: string) => Promise<SetUpOutcome>) =>
      afterSaves(async () => {
        const outcome = await send(currentRevision() ?? "");
        if (outcome.kind === "started") await reload();
        return outcome;
      }),
    [afterSaves, currentRevision, reload],
  );
  const setUp = useCallback(
    (answers: Omit<BackupSetUp, "revision">) =>
      outsideQueue((revision) => setUpBackup({ ...answers, revision })),
    [outsideQueue],
  );
  const replaceRepository = useCallback(
    (action: RepositoryAction) =>
      outsideQueue((revision) =>
        action.kind === "create"
          ? createRepository({ ...action.body, revision })
          : connectRepository({ ...action.body, revision }),
      ),
    [outsideQueue],
  );

  return {
    settings,
    setUp,
    replaceRepository,
    loadedVersion,
    status: queue.status,
    fieldErrors: queue.fieldErrors as Record<string, string>,
    loadError,
    reload,
    save,
    confirmSave,
    retry,
    locked: queue.locked,
  };
}
