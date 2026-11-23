// The clickable Backup prototype. One component owns every state the section
// can be in; each frame mounts it at a different starting point.
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { ClockCounterClockwiseIcon } from "@phosphor-icons/react/dist/csr/ClockCounterClockwise";
import { CloudArrowUpIcon } from "@phosphor-icons/react/dist/csr/CloudArrowUp";
import { CopyIcon } from "@phosphor-icons/react/dist/csr/Copy";
import { EyeIcon } from "@phosphor-icons/react/dist/csr/Eye";
import { EyeSlashIcon } from "@phosphor-icons/react/dist/csr/EyeSlash";
import { FolderOpenIcon } from "@phosphor-icons/react/dist/csr/FolderOpen";
import { HardDrivesIcon } from "@phosphor-icons/react/dist/csr/HardDrives";
import { InfoIcon } from "@phosphor-icons/react/dist/csr/Info";
import { LockKeyIcon } from "@phosphor-icons/react/dist/csr/LockKey";
import { PlusIcon } from "@phosphor-icons/react/dist/csr/Plus";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { useEffect, useState } from "react";
import { SaveStatus } from "../admin-settings/_parts";
import {
  type BackupRun,
  type BackupSettings,
  defaultSettings,
  type Destination,
  failingRuns,
  intervalChoices,
  restoreTarget,
  runs as healthyRuns,
} from "./_fixtures";
import { BackupPage, everyLabel, History, Panel, StatusPanel, WhereStored } from "./_parts";

type Stage = "off" | "setup" | "edit" | "on";
type Dialog = { kind: "restore" | "restoring" | "restored"; run: BackupRun } | null;
/** A backup in progress: waiting for jobs, then reading files. */
type Running = { step: number; first: boolean } | null;

export interface Start {
  stage: Stage;
  failing?: boolean;
  dialog?: "restore" | "restored";
  running?: boolean;
}

const RUN_STEPS = [
  "Waiting for the deploy of now-or-never to finish…",
  "Backing up… 1,206 of 5,142 files checked",
  "Backing up… 4,388 of 5,142 files checked",
  "Copying new files to iCloud Drive…",
];

export function BackupPrototype({ start }: { start: Start }) {
  const [stage, setStage] = useState<Stage>(start.stage);
  const [settings, setSettings] = useState<BackupSettings>(defaultSettings);
  const [failing, setFailing] = useState(start.failing ?? false);
  const [list, setList] = useState<BackupRun[]>(
    start.stage === "on" ? (start.failing ? failingRuns : healthyRuns) : [],
  );
  const [dialog, setDialog] = useState<Dialog>(
    start.dialog ? { kind: start.dialog, run: healthyRuns[1] } : null,
  );
  const [running, setRunning] = useState<Running>(start.running ? { step: 0, first: false } : null);
  const [fresh, setFresh] = useState<string | undefined>();
  const [savedNote, setSavedNote] = useState(false);

  // Step the fake backup along, then add its row to the history.
  useEffect(() => {
    if (!running) return;
    const t = setTimeout(() => {
      if (running.step + 1 < RUN_STEPS.length) {
        setRunning({ ...running, step: running.step + 1 });
        return;
      }
      const run: BackupRun = {
        id: `n${Date.now()}`,
        when: "Mon 23 Nov, 11:20",
        ago: "just now",
        result: "ok",
        detail: running.first
          ? "First backup · copied to iCloud Drive"
          : failing
            ? "Copied to iCloud Drive · it had missed 2 backups"
            : "Copied to iCloud Drive",
        added: running.first ? "20.1 GB" : "12 MB",
        duration: running.first ? "21 min 14 s" : "36 s",
        snapshot: `${Math.floor(Math.random() * 0xffffffff).toString(16)}`,
        kept: "recent",
      };
      setList((cur) => [run, ...cur]);
      setFresh(run.id);
      setFailing(false);
      setRunning(null);
    }, running.step === 0 ? 1800 : 1100);
    return () => clearTimeout(t);
  }, [running, failing]);

  // The restore runs for a moment, then reports.
  useEffect(() => {
    if (dialog?.kind !== "restoring") return;
    const t = setTimeout(() => setDialog({ kind: "restored", run: dialog.run }), 1600);
    return () => clearTimeout(t);
  }, [dialog]);

  useEffect(() => {
    if (!savedNote) return;
    const t = setTimeout(() => setSavedNote(false), 2200);
    return () => clearTimeout(t);
  }, [savedNote]);

  const backUp = () => setRunning({ step: 0, first: false });
  const restoreFrom = (run?: BackupRun) => {
    const pick = run ?? list.find((r) => r.snapshot);
    if (pick) setDialog({ kind: "restore", run: pick });
  };

  if (stage === "off") return <NotSetUp onStart={() => setStage("setup")} />;
  if (stage === "setup" || stage === "edit")
    return (
      <BackupPage>
        <SettingsForm
          mode={stage === "setup" ? "create" : "edit"}
          initial={settings}
          onCancel={() => setStage(stage === "setup" ? "off" : "on")}
          onSave={(next) => {
            setSettings(next);
            if (stage === "setup") {
              setList([]);
              setRunning({ step: 1, first: true });
            } else {
              setSavedNote(true);
            }
            setStage("on");
          }}
        />
      </BackupPage>
    );

  const last = list.find((r) => r.result !== "failed");
  const nextIn = Math.max(settings.intervalHours - 2, 1);
  const status = running
    ? {
        tone: "ok" as const,
        headline: running.first ? "Making the first backup" : last ? `Backed up ${last.ago}` : "Backing up",
        detail: running.first
          ? "The whole workspace, about 20 GB. Deploys, Prepare and AI runs you start wait until it's done."
          : "Jobs you start now wait until this backup finishes, usually under a minute.",
      }
    : failing
      ? {
          tone: "warn" as const,
          headline: "Backed up here 2 hours ago, not copied to iCloud Drive",
          detail: "The weekly check yesterday found a damaged file. Your backups are still readable, but run the check again.",
        }
      : {
          tone: "ok" as const,
          headline: last ? `Backed up ${last.ago}` : "No backups yet",
          detail: `Next backup in about ${last?.ago === "just now" ? settings.intervalHours : nextIn} hours · ${everyLabel(settings.intervalHours).toLowerCase()} · ${list.filter((r) => r.snapshot).length} backups kept`,
        };

  return (
    <>
      <BackupPage>
        {failing && !running && (
          <div className="adm-warn bk-banner" role="alert">
            <WarningIcon size={18} />
            <span>
              <strong>iCloud Drive hasn't had a backup for 2 days.</strong> The folder{" "}
              <span className="s-mono">{settings.destinations[0]?.path}</span> wasn't found. Check that iCloud for
              Windows is running and signed in. Backups on this computer are still running.
            </span>
            <button type="button" className="btn btn-secondary bk-banner__btn" onClick={backUp}>
              Try again
            </button>
          </div>
        )}
        {savedNote && (
          <div className="bk-saved" role="status">
            <SaveStatus state="saved" text={`Saved to settings.yaml · ${everyLabel(settings.intervalHours).toLowerCase()}`} />
          </div>
        )}
        <StatusPanel
          tone={status.tone}
          headline={status.headline}
          detail={status.detail}
          running={running ? RUN_STEPS[running.step] : undefined}
          onBackup={backUp}
          onRestore={() => restoreFrom()}
        />
        <History list={list} settings={settings} fresh={fresh} onRestore={restoreFrom} />
        <WhereStored
          settings={settings}
          repositoryChecked={failing ? "last check failed Sun 22 Nov" : "last passed Sun 22 Nov"}
          copyState={(d: Destination) =>
            failing && d.id === "icloud"
              ? { copied: "2 days ago", ok: false, problem: "Folder not found" }
              : { copied: last?.ago ?? "never", ok: true }
          }
          onEdit={() => setStage("edit")}
        />
      </BackupPage>
      {dialog && (
        <RestoreDialog
          dialog={dialog}
          choices={list.filter((r) => r.snapshot)}
          onPick={(run) => setDialog({ kind: "restore", run })}
          onCancel={() => setDialog(null)}
          onRestore={() => setDialog({ kind: "restoring", run: dialog.run })}
        />
      )}
    </>
  );
}

function NotSetUp({ onStart }: { onStart: () => void }) {
  return (
    <BackupPage>
      <Panel
        id="bk-off"
        title="Backups are off"
        lede="This workspace isn't backed up yet. Set up a backup and the app saves a copy of everything in it on a schedule, while it's open."
      >
        <ul className="bk-steps bk-intro">
          <li>
            <ClockCounterClockwiseIcon size={16} />
            <span>
              <strong>Every 12 hours, or as often as you choose.</strong> Each backup only stores what changed, so
              it usually takes under a minute. Deploys, Prepare and AI runs wait while it runs.
            </span>
          </li>
          <li>
            <LockKeyIcon size={16} />
            <span>
              <strong>Encrypted with your password.</strong> Without it no backup can be opened, so keep a copy in
              your password manager.
            </span>
          </li>
          <li>
            <CloudArrowUpIcon size={16} />
            <span>
              <strong>Stored here, copied to the cloud.</strong> Backups go to a folder on this computer first, then
              copy to destinations such as iCloud Drive or a NAS.
            </span>
          </li>
        </ul>
        <div className="bk-foot">
          <span className="bk-foot__note">
            Already have backups from another computer? Set up, then connect the existing backup folder instead of
            creating one.
          </span>
          <button type="button" className="btn btn-primary" onClick={onStart}>
            Set up backups
          </button>
        </div>
      </Panel>
    </BackupPage>
  );
}

function SettingsForm({
  mode,
  initial,
  onCancel,
  onSave,
}: {
  mode: "create" | "edit";
  initial: BackupSettings;
  onCancel: () => void;
  onSave: (s: BackupSettings) => void;
}) {
  const [s, setS] = useState(initial);
  const [pw, setPw] = useState("correct-horse-battery");
  const [pw2, setPw2] = useState("correct-horse-battery");
  const [show, setShow] = useState(false);
  const [stored, setStored] = useState(false);
  const set = <K extends keyof BackupSettings>(k: K, v: BackupSettings[K]) => setS((cur) => ({ ...cur, [k]: v }));

  const pwProblem = mode === "create" && (pw.length < 12 ? "Use at least 12 characters." : pw !== pw2 ? "The two passwords don't match." : null);
  const ready = mode === "edit" || (!pwProblem && stored);
  const changed = JSON.stringify(s) !== JSON.stringify(initial);

  const addDestination = () =>
    set("destinations", [
      ...s.destinations,
      { id: `d${s.destinations.length + 1}`, name: "Folder", path: "\\\\tower\\backups\\naturally-inked-studio", checked: "not checked yet" },
    ]);

  return (
    <Panel
      id="bk-setup"
      title={mode === "create" ? "Set up backups" : "Backup settings"}
      lede="Saved to the backup block in settings.yaml. The password goes in the workspace's .env file, never in settings.yaml."
    >
      <div className="bk-form">
        <div className="bk-field">
          <span className="bk-field__label">
            Backup folder
            <span className="bk-sub">On this computer, outside any synced folder. Backups and clean-up run here.</span>
          </span>
          <div className="bk-field__control">
            {mode === "create" ? (
              <>
                <div className="bk-inline">
                  <input className="input s-mono" aria-label="Backup folder" value={s.repository} onChange={(e) => set("repository", e.target.value)} />
                  <button type="button" className="btn btn-secondary">
                    <FolderOpenIcon size={16} /> Choose…
                  </button>
                </div>
                <span className="bk-sub">Empty folder · 183 GB free on C:</span>
              </>
            ) : (
              <>
                <span className="bk-readonly">
                  <HardDrivesIcon size={16} /> <span className="s-mono">{s.repository}</span>
                </span>
                <span className="bk-sub">Moving it starts a new backup history, so it can't be changed here.</span>
              </>
            )}
          </div>
        </div>

        <div className="bk-field">
          <span className="bk-field__label">
            Back up every
            <span className="bk-sub">Counted from the last backup that succeeded, and checked when the app starts.</span>
          </span>
          <div className="bk-field__control">
            <div className="seg bk-seg" role="radiogroup" aria-label="Back up every">
              {intervalChoices.map((h) => (
                <button
                  key={h}
                  type="button"
                  role="radio"
                  aria-checked={s.intervalHours === h}
                  className={s.intervalHours === h ? "seg-opt seg-opt--on" : "seg-opt"}
                  onClick={() => set("intervalHours", h)}
                >
                  {h % 24 === 0 ? `${h / 24} day${h === 24 ? "" : "s"}` : `${h} hours`}
                </button>
              ))}
            </div>
            <span className="bk-sub">
              {s.intervalHours < 12
                ? "More often means less to lose, and a short pause for your jobs more often."
                : s.intervalHours > 12
                  ? `Up to ${s.intervalHours / 24 >= 1 ? `${s.intervalHours / 24} day${s.intervalHours === 24 ? "" : "s"}` : `${s.intervalHours} hours`} of work could be lost if this computer fails.`
                  : "Recommended: at most half a day of work to lose."}
            </span>
          </div>
        </div>

        <div className="bk-field">
          <span className="bk-field__label">
            Password
            <span className="bk-sub">Encrypts every backup. Saved as ETSY_LISTINGS_BACKUP_PASSWORD in .env.</span>
          </span>
          <div className="bk-field__control">
            {mode === "create" ? (
              <>
                <div className="bk-inline bk-pw">
                  <input className="input" type={show ? "text" : "password"} aria-label="Password" placeholder="Password" value={pw} onChange={(e) => setPw(e.target.value)} />
                  <input className="input" type={show ? "text" : "password"} aria-label="Repeat password" placeholder="Repeat password" value={pw2} onChange={(e) => setPw2(e.target.value)} />
                  <button type="button" className="btn btn-secondary" aria-pressed={show} onClick={() => setShow(!show)}>
                    {show ? <EyeSlashIcon size={16} /> : <EyeIcon size={16} />} {show ? "Hide" : "Show"}
                  </button>
                </div>
                {pwProblem && <span className="adm-error-text">{pwProblem}</span>}
                <label className="bk-check">
                  <input type="checkbox" checked={stored} onChange={(e) => setStored(e.target.checked)} />
                  <span>
                    I've saved this password in my password manager. A backup restored to a new computer can't be
                    opened without it, because the copy of .env inside the backup is encrypted too.
                  </span>
                </label>
              </>
            ) : (
              <span className="bk-readonly">
                <LockKeyIcon size={16} /> Set, in .env
              </span>
            )}
          </div>
        </div>

        <div className="bk-field">
          <span className="bk-field__label">
            Copy to
            <span className="bk-sub">Each backup copies one way to these folders. An unavailable one catches up at the next run.</span>
          </span>
          <div className="bk-field__control">
            {s.destinations.length > 0 && (
              <div className="sa-table">
                {s.destinations.map((d) => (
                  <div className="sa-row bk-dest bk-dest--edit" key={d.id}>
                    <CloudArrowUpIcon size={18} />
                    <span className="sa-row__label">{d.name}</span>
                    <input
                      className="input s-mono"
                      aria-label={`${d.name} folder`}
                      value={d.path}
                      onChange={(e) =>
                        set(
                          "destinations",
                          s.destinations.map((x) => (x.id === d.id ? { ...x, path: e.target.value } : x)),
                        )
                      }
                    />
                    <button
                      type="button"
                      className="btn btn-ghost"
                      aria-label={`Remove ${d.name}`}
                      onClick={() => set("destinations", s.destinations.filter((x) => x.id !== d.id))}
                    >
                      <XIcon size={16} />
                    </button>
                  </div>
                ))}
              </div>
            )}
            {s.destinations.length === 0 && (
              <span className="bk-sub">No destinations. Backups stay on this computer only, so a failed disk loses them too.</span>
            )}
            <div>
              <button type="button" className="btn btn-secondary bk-add" onClick={addDestination}>
                <PlusIcon size={16} /> Add destination
              </button>
            </div>
          </div>
        </div>

        <div className="bk-field">
          <span className="bk-field__label">
            Keep
            <span className="bk-sub">Older backups are removed once a week.</span>
          </span>
          <div className="bk-field__control">
            <div className="bk-keep">
              <Num label="days of every backup" value={s.keepDays} onChange={(v) => set("keepDays", v)} />
              <Num label="weeks, latest each week" value={s.keepWeeks} onChange={(v) => set("keepWeeks", v)} />
              <Num label="months, latest each month" value={s.keepMonths} onChange={(v) => set("keepMonths", v)} />
            </div>
          </div>
        </div>

        <div className="bk-foot">
          {mode === "create" && (
            <span className="bk-foot__note">
              The first backup copies the whole workspace (about 20 GB) and can take 20 minutes or more. Jobs you
              start meanwhile wait until it finishes.
            </span>
          )}
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!ready || (mode === "edit" && !changed)}
            onClick={() => onSave(s)}
          >
            {mode === "create" ? "Create and back up now" : "Save"}
          </button>
        </div>
      </div>
    </Panel>
  );
}

function Num({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <label>
      <input
        className="input"
        inputMode="numeric"
        aria-label={label}
        value={value}
        onChange={(e) => {
          const n = Number(e.target.value.replace(/\D/g, ""));
          if (n > 0) onChange(n);
        }}
      />{" "}
      {label}
    </label>
  );
}

function RestoreDialog({
  dialog,
  choices,
  onPick,
  onCancel,
  onRestore,
}: {
  dialog: NonNullable<Dialog>;
  choices: BackupRun[];
  onPick: (run: BackupRun) => void;
  onCancel: () => void;
  onRestore: () => void;
}) {
  const { run } = dialog;
  const [target, setTarget] = useState(restoreTarget(run));
  useEffect(() => setTarget(restoreTarget(run)), [run]);
  const taken = target.replace(/\\+$/, "").toLowerCase() === "c:\\users\\admin\\naturally-inked-studio-workspace";

  if (dialog.kind === "restored")
    return (
      <div className="bk-scrim">
        <div className="bk-dialog" role="dialog" aria-modal="true" aria-labelledby="bk-done-title">
          <span className="bk-done-icon" aria-hidden="true">
            <CheckIcon size={24} weight="bold" />
          </span>
          <div>
            <h2 className="bk-dialog__title" id="bk-done-title">
              Restored 5,142 files
            </h2>
            <p className="bk-dialog__lede">The workspace from {run.when} is in this folder:</p>
          </div>
          <div className="bk-inline">
            <input className="input s-mono" aria-label="Restored folder" readOnly value={target} />
            <button type="button" className="btn btn-secondary">
              <CopyIcon size={16} /> Copy path
            </button>
          </div>
          <div>
            <p className="bk-dialog__lede">To use it, either:</p>
            <ol className="bk-steps">
              <li>
                Copy the files you need back into your workspace, for example one listing's{" "}
                <code className="s-mono">state.lock.json</code>.
              </li>
              <li>
                Or switch the app to it: set <code className="s-mono">ETSY_LISTINGS_ROOT</code> to this folder and
                restart the app.
              </li>
            </ol>
          </div>
          <div className="bk-dialog__foot">
            <button type="button" className="btn btn-primary" onClick={onCancel}>
              Done
            </button>
          </div>
        </div>
      </div>
    );

  const busy = dialog.kind === "restoring";
  return (
    <div className="bk-scrim">
      <div className="bk-dialog" role="dialog" aria-modal="true" aria-labelledby="bk-restore-title">
        <div>
          <h2 className="bk-dialog__title" id="bk-restore-title">
            Restore the backup from {run.when}
          </h2>
          <p className="bk-dialog__lede">
            The whole workspace as it was then, written into a new folder. Your current workspace isn't changed.
          </p>
        </div>
        <dl className="bk-facts">
          <dt>Backup</dt>
          <dd>
            <select
              className="bk-pick"
              aria-label="Backup to restore"
              value={run.id}
              disabled={busy}
              onChange={(e) => {
                const next = choices.find((c) => c.id === e.target.value);
                if (next) onPick(next);
              }}
            >
              {choices.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.when} ({r.ago})
                </option>
              ))}
            </select>
          </dd>
          <dt>Size</dt>
          <dd>20.1 GB · 5,142 files</dd>
          <dt>Listings</dt>
          <dd>34 listings, 19 batches</dd>
        </dl>
        <div className="bk-field__control">
          <span className="bk-field__label">Restore into</span>
          <div className="bk-inline">
            <input className="input s-mono" aria-label="Restore into" value={target} disabled={busy} onChange={(e) => setTarget(e.target.value)} />
            <button type="button" className="btn btn-secondary" disabled={busy}>
              <FolderOpenIcon size={16} /> Choose…
            </button>
          </div>
          {taken ? (
            <span className="adm-error-text">That's your live workspace. Choose a new, empty folder.</span>
          ) : (
            <span className="bk-sub">A new folder. A folder that already has files in it isn't accepted.</span>
          )}
        </div>
        {busy ? (
          <div className="bk-progress" role="status">
            <span className="bk-progress__bar" />
            <span className="bk-sub">Restoring… reading from the backup on this computer</span>
          </div>
        ) : (
          <p className="bk-note">
            <InfoIcon size={16} />
            <span>About 20 GB is read from the backup on this computer. Nothing is downloaded from iCloud Drive.</span>
          </p>
        )}
        <div className="bk-dialog__foot">
          <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" onClick={onRestore} disabled={busy || taken}>
            {busy ? "Restoring…" : "Restore to this folder"}
          </button>
        </div>
      </div>
    </div>
  );
}
