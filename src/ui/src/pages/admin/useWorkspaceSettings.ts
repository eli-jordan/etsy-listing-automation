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

const CHANGE_FOR_ERROR_PREFIX: Record<string, string> = {
  batch_ai: "concurrency",
  "ai.providers": "providers",
  "ai.step_limit_minutes": "step_limit_minutes",
  "ai.run_limit_minutes": "run_limit_minutes",
  market_seo: "weights",
  template_positions: "template_positions",
};

const answersError = (errorKey: string, changes: SettingsChanges) =>
  errorKey.startsWith("backup")
    ? Object.keys(changes).some((change) => change.startsWith("backup"))
    : Object.entries(CHANGE_FOR_ERROR_PREFIX).some(
        ([prefix, change]) => errorKey.startsWith(prefix) && change in changes,
      );

export type RepositoryAction =
  | { kind: "create"; body: Omit<NewRepository, "revision"> }
  | { kind: "connect"; body: Omit<ConnectRepository, "revision"> };

export function useWorkspaceSettings() {
  const [settings, setSettings] = useState<WorkspaceSettings | null>(null);
  const queue = useSaveQueue({
    send,
    answersError,
    fallbackMessage: "Could not save settings.yaml",
  });
  const { save: enqueue, writeOutside } = queue;
  const clear = useCallback(() => setSettings(null), []);
  const { loadedVersion, loadError, reload } = useQueuedFile({
    load: loadSettings,
    queue,
    onLoaded: setSettings,
    onRefused: clear,
    fallback: "Could not read settings.yaml",
  });

  const confirmSave = useCallback(
    (changes: SettingsChanges) => enqueue(changes, { retain: false }),
    [enqueue],
  );

  const outsideQueue = useCallback(
    (send: (revision: string) => Promise<SetUpOutcome>) =>
      writeOutside(async (revision) => {
        const outcome = await send(revision);
        if (outcome.kind === "started") await reload();
        return outcome;
      }),
    [writeOutside, reload],
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
    save: queue.queueSave,
    confirmSave,
    retry: queue.queueRetry,
    locked: queue.locked,
  };
}
