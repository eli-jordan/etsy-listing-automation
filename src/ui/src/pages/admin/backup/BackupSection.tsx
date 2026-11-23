// Admin › Settings › Backup (workspace-backup plan, PR 6): Backups off, the
// set-up form, Status and history, and Setup. Status comes from the shell's
// one poll (`useBackupStatus`); Setup saves through settings.yaml's revision
// check, like the AI section. Restore is in Restore.tsx; the missing-repository
// actions are in MissingRepository.tsx (PR 8).
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { useEffect, useRef, useState } from "react";
import {
  type BackupSettings,
  type BackupStatus,
  type DestinationStatus,
  getBackupHistory,
  type HistoryEntry,
  type RetentionSettings,
  repairDestination,
  runBackup,
  type SetUpOutcome,
} from "../../../api/backup";
import type { SettingsChanges } from "../../../api/workspaceSettings";
import { useBackupStatus } from "../../../shell/backupStatus";
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
  type RepositoryMode,
  RepositoryDialog,
} from "./MissingRepository";
import { RestoreDialogs, RestoreStrip } from "./Restore";
import { useRestore } from "./useRestore";
import {
  type BackupAnswers,
  NEW_BACKUP,
  repairNote,
  retryable,
  runningLine,
  summary,
} from "./backupText";
import "./backup.css";

export type BackupPage = "status" | "setup";

/** What a settings.yaml save answered, as `useWorkspaceSettings` reports it. */
export type SaveAnswer =
  | { kind: "saved" }
  | { kind: "conflict"; message: string }
  | { kind: "invalid"; message: string; fieldErrors: Partial<Record<string, string>> }
  | null;

const RELOAD = "settings.yaml changed on disk. Nothing was overwritten. Reload, then try again.";

/** A settings save's `conflict` is always its 412 (`saveSettings`), and
 * set-up reports its 412 as `stale`: both mean reload. Set-up's other
 * conflicts (409) say what is wrong themselves. */
function refusal(outcome: Exclude<SetUpOutcome, { kind: "started" }>): string;
function refusal(outcome: Exclude<SaveAnswer, null>, settingsSave: true): string | null;
function refusal(
  outcome: Exclude<SaveAnswer | SetUpOutcome, null | { kind: "started" }>,
  settingsSave = false,
): string | null {
  if (outcome.kind === "saved") return null;
  if (outcome.kind === "stale" || (settingsSave && outcome.kind === "conflict")) return RELOAD;
  const fields = Object.values(outcome.kind === "invalid" ? outcome.fieldErrors : {});
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
}: {
  page: BackupPage;
  onPage: (page: BackupPage) => void;
  /** settings.yaml's `backup:` block; null while off, undefined while loading. */
  saved: BackupSettings | null | undefined;
  setUp: (answers: BackupAnswers & { password: string }) => Promise<SetUpOutcome>;
  replaceRepository: (action: RepositoryAction) => Promise<SetUpOutcome>;
  save: (changes: SettingsChanges) => Promise<SaveAnswer>;
}) {
  const { status, error, readAt, refresh } = useBackupStatus();
  const [creating, setCreating] = useState(false);

  if (!status)
    return error ? (
      <div className="adm-warn" role="alert">
        <WarningIcon size={18} />
        <span>{error}</span>
      </div>
    ) : (
      <p role="status">Loading backups…</p>
    );

  if (!status.enabled) {
    if (!creating) return <NotSetUp onStart={() => setCreating(true)} />;
    const create = async (answers: BackupAnswers, password: string): Answer => {
      try {
        const outcome = await setUp({ ...answers, password });
        if (outcome.kind !== "started") return refusal(outcome);
        await refresh();
        setCreating(false);
        onPage("status");
        return null;
      } catch (e) {
        return failure(e, "Could not set up backups");
      }
    };
    return (
      <BackupForm
        mode="create"
        initial={NEW_BACKUP}
        onCancel={() => setCreating(false)}
        onCreate={create}
      />
    );
  }

  if (page === "setup") {
    if (!saved) return <p role="status">Loading settings…</p>;
    const edit = async (answers: BackupAnswers, base: BackupAnswers): Answer => {
      try {
        const refused = await save(changes(answers, base));
        if (refused === null) return RELOAD;
        const message = refusal(refused, true);
        if (!message) void refresh();
        return message;
      } catch (e) {
        return failure(e, "Could not save settings.yaml");
      }
    };
    return <BackupForm mode="edit" initial={answersOf(saved)} onSave={edit} />;
  }

  return (
    <StatusPage
      status={status}
      now={readAt}
      retention={saved?.retention ?? NEW_BACKUP.retention}
      refresh={refresh}
      replaceRepository={replaceRepository}
      onSetup={() => onPage("setup")}
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
  status,
  now,
  retention,
  refresh,
  replaceRepository,
  onSetup,
}: {
  status: BackupStatus;
  now: number;
  retention: RetentionSettings;
  refresh: () => Promise<unknown>;
  replaceRepository: (action: RepositoryAction) => Promise<SetUpOutcome>;
  onSetup: () => void;
}) {
  const history = useHistory(status);
  const restore = useRestore(status, refresh);
  const [note, setNote] = useState<string | null>(null);
  const [repair, setRepair] = useState<Repair | null>(null);
  const [replacing, setReplacing] = useState<RepositoryMode | null>(null);
  const warnings = status.warnings.filter((w) => w.banner);
  const retry = warnings.filter(retryable);
  const missing = warnings.find((w) => w.kind === "repository_missing");
  const changed = status.destinations.filter((d) =>
    warnings.some((w) => w.kind === "changed" && w.destination === d.path),
  );
  const { tone, headline, detail } = summary(status, now);

  const backUp = () => {
    setNote(null);
    runBackup().then(refresh, (e: unknown) => setNote(failure(e, "Could not start a backup")));
  };
  const replace = async (action: RepositoryAction): Promise<string | null> => {
    try {
      const outcome = await replaceRepository(action);
      if (outcome.kind !== "started") return refusal(outcome);
      setReplacing(null);
      void refresh();
      return null;
    } catch (e) {
      return failure(e, "Could not reach the server");
    }
  };
  const runRepair = async (destination: DestinationStatus) => {
    setRepair({ destination, working: true, error: null });
    try {
      const result = await repairDestination(destination.path);
      setRepair(null);
      setNote(repairNote(destination.path, result));
      void refresh();
    } catch (e) {
      setRepair({ destination, working: false, error: failure(e, "Could not repair the copy") });
    }
  };

  return (
    <>
      {missing && <MissingRepositoryBanner warning={missing} onAction={setReplacing} />}
      {changed.map((d) => (
        <ChangedFilesBanner
          key={d.path}
          destination={d}
          onRepair={() => setRepair({ destination: d, working: false, error: null })}
        />
      ))}
      {retry.length > 0 && (
        <div className="adm-warn bk-banner" role="alert">
          <WarningIcon size={18} />
          <span>
            <strong>{retry[0]?.message}</strong>{" "}
            {retry
              .slice(1)
              .map((w) => w.message)
              .join(" ")}
          </span>
          <button
            type="button"
            className="btn btn-secondary bk-banner__btn"
            disabled={Boolean(status.running)}
            onClick={backUp}
          >
            Try again
          </button>
        </div>
      )}
      <StatusPanel
        tone={tone}
        headline={headline}
        detail={detail}
        running={status.running ? runningLine(status.running) : undefined}
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
              onClick={() => setNote(null)}
            >
              <XIcon size={16} />
            </button>
          </div>
        )}
      </StatusPanel>
      <StoragePipeline status={status} now={now} onSetup={onSetup} />
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
function useHistory(status: BackupStatus) {
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [fresh, setFresh] = useState<string | undefined>();
  const opened = useRef<number | null>(null);
  const key = `${status.running ? "running" : "idle"} ${status.last_success ?? ""}`;
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
