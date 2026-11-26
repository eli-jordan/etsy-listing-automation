import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { useEffect, useRef, useState } from "react";
import {
  type BackupConnected,
  type BackupSettings,
  type DestinationStatus,
  getBackupHistory,
  type HistoryEntry,
  type RetentionSettings,
  repairDestination,
  runBackup,
  type SetUpOutcome,
} from "../../../api/backup";
import type { Refusal } from "../../../api/refusal";
import type { SettingsChanges } from "../../../api/workspaceSettings";
import type { BackupsOn } from "../../../shell/backupAttention";
import { FAST_POLL_MS, useBackupStatus } from "../../../shell/backupStatus";
import type { RepositoryAction } from "../useWorkspaceSettings";
import { type Answer, BackupForm } from "./BackupForm";
import {
  ChangedFilesBanner,
  History,
  NotSetUp,
  RepairDialog,
  StatusPanel,
  StoragePipeline,
} from "./BackupPanels";
import {
  MissingRepositoryBanner,
  type Refused,
  type RepositoryMode,
  RepositoryDialog,
} from "./MissingRepository";
import { RestoreDialogs, RestoreStrip } from "./Restore";
import { useRestore } from "./useRestore";
import {
  type BackupAnswers,
  connectedNote,
  NEW_BACKUP,
  repairNote,
  runningLine,
  summary,
} from "./backupText";
import "./backup.css";

export type BackupPage = "status" | "setup";

/** What a settings.yaml save answered, as `useWorkspaceSettings` reports
 * it: null when an earlier save already found the file stale. */
export type SaveAnswer = { kind: "saved" } | Refusal | null;

const RELOAD = "settings.yaml changed on disk. Nothing was overwritten. Reload, then try again.";

function refusal(outcome: Refusal): string {
  if (outcome.kind === "stale") return RELOAD;
  const fields = Object.values(outcome.fieldErrors).filter(
    (text) => !outcome.message.includes(text),
  );
  return [outcome.message, ...fields].filter(Boolean).join(" ");
}

function failure(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function BackupSection({
  page,
  onPage,
  saved,
  setUp,
  replaceRepository,
  save,
  connected = null,
  onConnectedSeen = () => undefined,
}: {
  page: BackupPage;
  onPage: (page: BackupPage) => void;
  saved: BackupSettings | null | undefined;
  setUp: (answers: BackupAnswers & { password: string }) => Promise<SetUpOutcome>;
  replaceRepository: (action: RepositoryAction) => Promise<SetUpOutcome>;
  save: (changes: SettingsChanges) => Promise<SaveAnswer>;
  /** The backup set-up connected, kept above this section: the reload after
   * set-up remounts it. Shown as a note until dismissed. */
  connected?: BackupConnected | null;
  onConnectedSeen?: () => void;
}) {
  const { view, readAt, refresh } = useBackupStatus();
  const [creating, setCreating] = useState(false);

  if (view.state === "loading") return <p role="status">Loading backups…</p>;
  if (view.state === "error")
    return (
      <div className="adm-warn" role="alert">
        <WarningIcon size={18} />
        <span>{view.error}</span>
      </div>
    );

  if (view.state === "off") {
    if (!creating) return <NotSetUp onStart={() => setCreating(true)} />;
    const create = async (answers: BackupAnswers, password: string): Answer => {
      // A destination that already holds a backup is connected, which can
      // take minutes; the status says so while the request runs.
      const polling = setInterval(() => void refresh(), FAST_POLL_MS);
      try {
        const outcome = await setUp({ ...answers, password });
        if (outcome.kind !== "started") return refusal(outcome);
        await refresh();
        setCreating(false);
        onPage("status");
        return null;
      } catch (e) {
        return failure(e, "Could not set up backups");
      } finally {
        clearInterval(polling);
      }
    };
    return (
      <BackupForm
        mode="create"
        initial={NEW_BACKUP}
        status={view.status}
        onCancel={() => setCreating(false)}
        onCreate={create}
      />
    );
  }

  if (page === "setup") {
    if (!saved) return <p role="status">Loading settings…</p>;
    const edit = async (answers: BackupAnswers, base: BackupAnswers): Answer => {
      try {
        const answer = await save(changes(answers, base));
        if (answer === null) return RELOAD;
        if (answer.kind !== "saved") return refusal(answer);
        void refresh();
        return null;
      } catch (e) {
        return failure(e, "Could not save settings.yaml");
      }
    };
    return <BackupForm mode="edit" initial={answersOf(saved)} status={view.status} onSave={edit} />;
  }

  return (
    <StatusPage
      view={view}
      now={readAt}
      retention={saved?.retention ?? NEW_BACKUP.retention}
      refresh={refresh}
      replaceRepository={replaceRepository}
      onSetup={() => onPage("setup")}
      setUpNote={connected ? connectedNote(view.status, connected) : null}
      onSetUpNoteSeen={onConnectedSeen}
    />
  );
}

function answersOf(saved: BackupSettings): BackupAnswers {
  return {
    repository: saved.repository,
    destinations: saved.destinations,
    interval_hours: saved.interval_hours,
    retention: saved.retention ?? NEW_BACKUP.retention,
  };
}

/** Only what Setup changed: each key is its own settings.yaml edit. */
function changes(answers: BackupAnswers, base: BackupAnswers): SettingsChanges {
  const differs = (a: unknown, b: unknown) => JSON.stringify(a) !== JSON.stringify(b);
  return {
    ...(differs(answers.destinations, base.destinations) && {
      backup_destinations: answers.destinations,
    }),
    ...(answers.interval_hours !== base.interval_hours && {
      backup_interval_hours: answers.interval_hours,
    }),
    ...(differs(answers.retention, base.retention) && { backup_retention: answers.retention }),
  };
}

type Repair = { destination: DestinationStatus; working: boolean; error: string | null };

function StatusPage({
  view,
  now,
  retention,
  refresh,
  replaceRepository,
  onSetup,
  setUpNote,
  onSetUpNoteSeen,
}: {
  view: BackupsOn;
  now: number;
  retention: RetentionSettings;
  refresh: () => Promise<unknown>;
  replaceRepository: (action: RepositoryAction) => Promise<SetUpOutcome>;
  onSetup: () => void;
  setUpNote: string | null;
  onSetUpNoteSeen: () => void;
}) {
  const { status } = view;
  const history = useHistory(view);
  const restore = useRestore(view, refresh);
  const [ownNote, setNote] = useState<string | null>(null);
  const note = ownNote ?? setUpNote;
  const [repair, setRepair] = useState<Repair | null>(null);
  const [replacing, setReplacing] = useState<RepositoryMode | null>(null);
  const { tone, headline, detail } = summary(view, now);

  const backUp = () => {
    setNote(null);
    runBackup().then(refresh, (e: unknown) => setNote(failure(e, "Could not start a backup")));
  };
  const replace = async (action: RepositoryAction): Promise<Refused | null> => {
    try {
      const outcome = await replaceRepository(action);
      if (outcome.kind !== "started")
        return {
          message: refusal(outcome),
          ...(outcome.kind === "refused" &&
            outcome.connectFrom && { connectFrom: outcome.connectFrom }),
        };
      setReplacing(null);
      void refresh();
      return null;
    } catch (e) {
      return { message: failure(e, "Could not reach the server") };
    }
  };
  const runRepair = async (destination: DestinationStatus) => {
    setRepair({ destination, working: true, error: null });
    try {
      const result = await repairDestination(destination.path);
      setRepair(null);
      setNote(repairNote(destination, result));
      void refresh();
    } catch (e) {
      setRepair({ destination, working: false, error: failure(e, "Could not repair the copy") });
    }
  };

  return (
    <>
      {view.attention.map((item) => {
        if (item.action === "connect")
          return (
            <MissingRepositoryBanner key="connect" warning={item.warning} onAction={setReplacing} />
          );
        if (item.action === "repair") {
          const { destination } = item;
          return (
            <ChangedFilesBanner
              key={destination.path}
              destination={destination}
              onRepair={() => setRepair({ destination, working: false, error: null })}
            />
          );
        }
        const [first, ...rest] = item.warnings;
        return (
          <div key="retry" className="adm-warn bk-banner" role="alert">
            <WarningIcon size={18} />
            <span>
              <strong>{first?.message}</strong> {rest.map((w) => w.message).join(" ")}
            </span>
            <button
              type="button"
              className="btn btn-secondary bk-banner__btn"
              disabled={view.running}
              onClick={backUp}
            >
              Try again
            </button>
          </div>
        );
      })}
      <StatusPanel
        tone={tone}
        headline={headline}
        detail={detail}
        running={view.running}
        runningLine={status.running ? runningLine(status, status.running) : undefined}
        restore={{
          disabled: restore.busy || !status.repository?.snapshots,
          onClick: () => restore.begin(),
        }}
        onBackup={backUp}
      >
        <RestoreStrip flow={restore} />
        {restore.error && (
          <p className="adm-error-text" role="alert">
            {restore.error}
          </p>
        )}
        {note && (
          <div className="bk-strip" role="status">
            <span className="bk-strip__text">
              <strong>{note}</strong>
            </span>
            <button
              type="button"
              className="btn btn-ghost"
              aria-label="Dismiss"
              onClick={() => {
                setNote(null);
                onSetUpNoteSeen();
              }}
            >
              <XIcon size={16} />
            </button>
          </div>
        )}
      </StatusPanel>
      <StoragePipeline view={view} now={now} onSetup={onSetup} />
      {history.error && (
        <p className="adm-error-text" role="alert">
          {history.error}
        </p>
      )}
      <History
        entries={history.entries}
        retention={retention}
        fresh={history.fresh}
        now={now}
        restoreBusy={restore.busy}
        onRestore={restore.begin}
      />
      <RestoreDialogs flow={restore} now={now} />
      {replacing && (
        <RepositoryDialog
          mode={replacing}
          repository={status.repository?.path ?? ""}
          passwordStored={status.repository?.password_stored ?? false}
          passwordMinLength={status.password_min_length}
          onCancel={() => setReplacing(null)}
          onSubmit={replace}
        />
      )}
      {repair && (
        <RepairDialog
          destination={repair.destination}
          working={repair.working}
          error={repair.error}
          onCancel={() => setRepair(null)}
          onRepair={() => void runRepair(repair.destination)}
        />
      )}
    </>
  );
}

/** The history, read again whenever a run starts or ends. The newest run,
 * when it finished after the page opened, is `fresh`: briefly highlighted. */
function useHistory({ status, running }: BackupsOn) {
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [fresh, setFresh] = useState<string | undefined>();
  const opened = useRef<number | null>(null);
  const key = `${running ? "running" : "idle"} ${status.last_success ?? ""}`;
  useEffect(() => {
    opened.current ??= Date.now();
    const since = opened.current;
    let active = true;
    getBackupHistory().then(
      (list) => {
        if (!active) return;
        const top = list[0]?.run;
        if (top && Date.parse(top.finished_at) > since) setFresh(top.started_at);
        setEntries(list);
        setError(null);
      },
      (e: unknown) => {
        if (active) setError(failure(e, "Could not read the backup history"));
      },
    );
    return () => {
      active = false;
    };
  }, [key]);
  return { entries, error, fresh };
}
