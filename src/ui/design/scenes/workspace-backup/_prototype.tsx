// The clickable Backup prototype. One component owns every state the app can
// be in for backups (including the page the seller is on, so a failing backup
// can show its warning elsewhere); each frame mounts it at a different
// starting point.
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { CircleNotchIcon } from "@phosphor-icons/react/dist/csr/CircleNotch";
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
import { type ReactNode, useEffect, useState } from "react";
import { STATUS_LABELS } from "../../../src/components/StatusTag";
import { SaveStatus } from "../admin-settings/_parts";
import {
  type BackupRun,
  type BackupSettings,
  defaultSettings,
  type Destination,
  failingRuns,
  changedFiles,
  changedRuns,
  intervalChoices,
  restoreTarget,
  runs as healthyRuns,
  snapshotSize,
} from "./_fixtures";
import {
  type AppPage,
  BackupPage,
  BackupShell,
  everyLabel,
  History,
  Panel,
  Progress,
  StatusPanel,
  StoragePipeline,
} from "./_parts";

type Stage = "off" | "setup" | "edit" | "on";
type Dialog = { kind: "restore" | "restored"; run: BackupRun; target?: string } | null;
/** A backup in progress: waiting for jobs, then reading files. */
type Running = { step: number; first: boolean } | null;
/** A restore in progress. `open` is whether its dialog is showing. */
type Restoring = { run: BackupRun; target: string; pct: number; open: boolean } | null;

export interface Start {
  stage: Stage;
  failing?: boolean;
  dialog?: "restore" | "restoring" | "restored";
  running?: boolean;
  restoringInBackground?: boolean;
  page?: AppPage;
  /** iCloud Drive holds changed or unexpected files. */
  changed?: boolean;
}

const RUN_STEPS = [
  "Waiting for the deploy of now-or-never to finish…",
  "Backing up… 1,206 of 5,142 files checked",
  "Backing up… 4,388 of 5,142 files checked",
  "Copying new files to iCloud Drive…",
];

/** A whole-workspace restore from local disk, roughly. */
const RESTORE_MINUTES = 9;

export function BackupPrototype({ start }: { start: Start }) {
  const [page, setPage] = useState<AppPage>(start.page ?? "admin");
  const [stage, setStage] = useState<Stage>(start.stage);
  const [settings, setSettings] = useState<BackupSettings>(defaultSettings);
  const [failing, setFailing] = useState(start.failing ?? false);
  const [changed, setChanged] = useState(start.changed ?? false);
  const [repair, setRepair] = useState<"confirm" | "working" | null>(null);
  const [list, setList] = useState<BackupRun[]>(
    start.stage === "on" || start.stage === "edit"
      ? start.failing
        ? failingRuns
        : start.changed
          ? changedRuns
          : healthyRuns
      : [],
  );
  const [dialog, setDialog] = useState<Dialog>(
    start.dialog === "restore" || start.dialog === "restored"
      ? { kind: start.dialog, run: healthyRuns[1], target: restoreTarget(healthyRuns[1]) }
      : null,
  );
  const [restoring, setRestoring] = useState<Restoring>(
    start.dialog === "restoring" || start.restoringInBackground
      ? {
          run: healthyRuns[1],
          target: restoreTarget(healthyRuns[1]),
          pct: start.restoringInBackground ? 0.62 : 0.38,
          open: !start.restoringInBackground,
        }
      : null,
  );
  const [restoreNote, setRestoreNote] = useState<{ text: string; done?: { run: BackupRun; target: string } } | null>(null);
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

  // The restore creeps along; at the end it reports in its dialog, or on the
  // page when the dialog was closed.
  useEffect(() => {
    if (!restoring) return;
    const t = setTimeout(() => {
      const pct = Math.min(1, restoring.pct + 0.02);
      if (pct < 1) {
        setRestoring({ ...restoring, pct });
        return;
      }
      const done = { run: restoring.run, target: restoring.target };
      setRestoring(null);
      if (restoring.open) setDialog({ kind: "restored", ...done });
      else setRestoreNote({ text: `Restored the backup from ${done.run.when}.`, done });
    }, 300);
    return () => clearTimeout(t);
  }, [restoring]);

  useEffect(() => {
    if (!savedNote) return;
    const t = setTimeout(() => setSavedNote(false), 2200);
    return () => clearTimeout(t);
  }, [savedNote]);

  // Repair sets the files aside, then copies again.
  useEffect(() => {
    if (repair !== "working") return;
    const t = setTimeout(() => {
      setRepair(null);
      setChanged(false);
      setRestoreNote({
        text: `Repaired the iCloud Drive copy. ${changedFiles.length} files were set aside in naturally-inked-studio-backups-set-aside-2026-11-23, next to it.`,
      });
    }, 1400);
    return () => clearTimeout(t);
  }, [repair]);

  const backUp = () => setRunning({ step: 0, first: false });
  const restoreFrom = (run?: BackupRun) => {
    const pick = run ?? list.find((r) => r.snapshot);
    if (pick) setDialog({ kind: "restore", run: pick });
  };
  const on = stage === "on" || stage === "edit";
  const warning =
    failing && !running
      ? "iCloud Drive hasn't had a copy for 2 days, and yesterday's weekly check found a damaged file."
      : changed
        ? "A file in the iCloud Drive copy changed after it was copied, and an unexpected file appeared. Copying there has stopped."
        : undefined;

  const shell = (body: ReactNode) => (
    <BackupShell
      page={page}
      warning={warning}
      onGo={(p) => {
        setPage(p);
        if (p === "admin" && stage === "edit") setStage("on");
      }}
    >
      {body}
    </BackupShell>
  );

  if (page === "dashboard") return shell(<DashboardMock />);

  const adminPage = (sub: "overview" | "settings" | undefined, body: ReactNode) => (
    <BackupPage
      sub={sub}
      on={on}
      warn={warning !== undefined}
      interval={settings.intervalHours}
      onSub={(s) => setStage(s === "settings" ? "edit" : "on")}
    >
      {body}
    </BackupPage>
  );

  if (stage === "off") return shell(adminPage(undefined, <NotSetUp onStart={() => setStage("setup")} />));
  if (stage === "setup" || stage === "edit")
    return shell(
      adminPage(
        stage === "edit" ? "settings" : undefined,
        <SettingsForm
          key={stage}
          mode={stage === "setup" ? "create" : "edit"}
          initial={settings}
          onCancel={() => setStage(stage === "setup" ? "off" : "on")}
          onSave={(next) => {
            setSettings(next);
            if (stage === "setup") {
              setList([]);
              setRunning({ step: 1, first: true });
              setStage("on");
            } else {
              setSavedNote(true);
            }
          }}
          savedNote={savedNote}
        />,
      ),
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
    : changed
      ? {
          tone: "warn" as const,
          headline: "Backed up here 2 hours ago, iCloud Drive copy stopped",
          detail: "Something changed files in the iCloud Drive copy. Nothing there was overwritten. The backups on this computer are fine.",
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
      {shell(
        adminPage(
          "overview",
          <>
            {changed && <ChangedFilesBanner onRepair={() => setRepair("confirm")} />}
            {warning && !changed && (
              <div className="adm-warn bk-banner" role="alert">
                <WarningIcon size={18} />
                <span>
                  <strong>iCloud Drive hasn't had a copy for 2 days.</strong> The folder{" "}
                  <span className="s-mono">{settings.destinations[0]?.path}</span> wasn't found. Check that iCloud
                  for Windows is running and signed in. Backups on this computer are still running.
                </span>
                <button type="button" className="btn btn-secondary bk-banner__btn" onClick={backUp}>
                  Try again
                </button>
              </div>
            )}
            <StatusPanel
              tone={status.tone}
              headline={status.headline}
              detail={status.detail}
              running={running ? RUN_STEPS[running.step] : undefined}
              restoreBusy={restoring !== null}
              onBackup={backUp}
              onRestore={() => restoreFrom()}
            >
              {restoring && !restoring.open && (
                <RestoreStrip restoring={restoring} onShow={() => setRestoring({ ...restoring, open: true })} />
              )}
              {!restoring && restoreNote && (
                <div className="bk-strip" role="status">
                  <span className="bk-strip__text">
                    <strong>{restoreNote.text}</strong>
                    {restoreNote.done && <span className="s-mono bk-sub">{restoreNote.done.target}</span>}
                  </span>
                  {restoreNote.done && (
                    <button
                      type="button"
                      className="btn btn-secondary"
                      onClick={() => {
                        const done = restoreNote.done!;
                        setRestoreNote(null);
                        setDialog({ kind: "restored", ...done });
                      }}
                    >
                      Show
                    </button>
                  )}
                  <button type="button" className="btn btn-ghost" aria-label="Dismiss" onClick={() => setRestoreNote(null)}>
                    <XIcon size={16} />
                  </button>
                </div>
              )}
            </StatusPanel>
            <StoragePipeline
              settings={settings}
              onSettings={() => setStage("edit")}
              facts={{
                workspace: "20.1 GB · 5,142 files",
                stored: `23.4 GB for ${list.filter((r) => r.snapshot).length} backups`,
                storedState: failing ? { ok: false, text: "Check failed" } : { ok: true, text: "Checked Sun 22 Nov" },
                copyState: (d: Destination) =>
                  changed && d.id === "icloud"
                    ? { ok: false, text: `${changedFiles.length} files to check`, copied: "14 hours ago" }
                    : failing && d.id === "icloud"
                    ? { ok: false, text: "Folder not found", copied: "2 days ago" }
                    : { ok: true, text: "Up to date", copied: last?.ago ?? "never" },
              }}
            />
            <History list={list} settings={settings} fresh={fresh} restoreBusy={restoring !== null} onRestore={restoreFrom} />
          </>,
        ),
      )}
      {repair && (
        <RepairDialog working={repair === "working"} onCancel={() => setRepair(null)} onRepair={() => setRepair("working")} />
      )}
      {dialog?.kind === "restore" && (
        <RestoreDialog
          run={dialog.run}
          choices={list.filter((r) => r.snapshot)}
          onPick={(run) => setDialog({ kind: "restore", run })}
          onCancel={() => setDialog(null)}
          onRestore={(target) => {
            setDialog(null);
            setRestoreNote(null);
            setRestoring({ run: dialog.run, target, pct: 0, open: true });
          }}
        />
      )}
      {restoring?.open && (
        <RestoringDialog
          restoring={restoring}
          onHide={() => setRestoring({ ...restoring, open: false })}
          onCancel={() => {
            setRestoring(null);
            setRestoreNote({
              text: `Restore stopped at ${Math.round(restoring.pct * 100)}%. The folder holds the files restored so far; delete it before restoring there again.`,
            });
          }}
        />
      )}
      {dialog?.kind === "restored" && (
        <RestoredDialog run={dialog.run} target={dialog.target ?? restoreTarget(dialog.run)} onDone={() => setDialog(null)} />
      )}
    </>
  );
}

/** What the copy found in iCloud Drive, with the one way to fix it. */
function ChangedFilesBanner({ onRepair }: { onRepair: () => void }) {
  return (
    <div className="adm-warn bk-banner bk-changed" role="alert">
      <WarningIcon size={18} />
      <div className="bk-changed__body">
        <span>
          <strong>Files in the iCloud Drive copy changed after they were copied.</strong> restic never changes a file
          once written, so iCloud, another program or a person did. Copying to iCloud Drive has stopped, and nothing
          there was overwritten.
        </span>
        <ul className="bk-changed__list">
          {changedFiles.map((f) => (
            <li key={f.path}>
              <span className="s-mono">{f.path}</span>
              <span className="bk-pill bk-pill--warn">{f.kind === "changed" ? "Changed" : "Unexpected"}</span>
              <span className="bk-changed__why">{f.detail}</span>
            </li>
          ))}
        </ul>
        <div>
          <button type="button" className="btn btn-secondary" onClick={onRepair}>
            Repair the iCloud Drive copy…
          </button>
        </div>
      </div>
    </div>
  );
}

function RepairDialog({ working, onCancel, onRepair }: { working: boolean; onCancel: () => void; onRepair: () => void }) {
  return (
    <div className="bk-scrim">
      <div className="bk-dialog" role="dialog" aria-modal="true" aria-labelledby="bk-repair-title">
        <div>
          <h2 className="bk-dialog__title" id="bk-repair-title">
            Repair the iCloud Drive copy
          </h2>
          <p className="bk-dialog__lede">
            The {changedFiles.length} files move out of the copy into a folder beside it, so you can look at them.
            Nothing is deleted. Then the copy runs again from the backup storage folder on this computer.
          </p>
        </div>
        <dl className="bk-facts">
          <dt>Set aside in</dt>
          <dd className="s-mono">naturally-inked-studio-backups-set-aside-2026-11-23</dd>
          <dt>Copied again</dt>
          <dd>1 file, 16.8 MB</dd>
        </dl>
        {working && (
          <p className="bk-status__running" role="status">
            <CircleNotchIcon size={14} className="adm-spin" /> Setting files aside and copying…
          </p>
        )}
        <div className="bk-dialog__foot">
          <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={working}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" onClick={onRepair} disabled={working}>
            Set aside and copy again
          </button>
        </div>
      </div>
    </div>
  );
}

/** The Dashboard as it is today, with made-up counts. */
function DashboardMock() {
  const cards = [
    { status: "draft", value: 6, caption: "not applied yet" },
    { status: "deployed", value: 3, caption: "applied — publish on Etsy" },
    { status: "live", value: 25, caption: "published on Etsy" },
    { status: "dirty", value: 2, caption: "live, but edited since" },
  ] as const;
  return (
    <div>
      <div className="page-head">
        <h1 className="page-head__title">Dashboard</h1>
        <div className="page-head__actions">
          <button type="button" className="btn btn-primary">
            + New listing
          </button>
        </div>
      </div>
      <div className="stat-row">
        {cards.map((c) => (
          <div key={c.status} className="card stat-card">
            <span className="stat-card__label">{STATUS_LABELS[c.status]}</span>
            <span className="stat-card__value">{c.value}</span>
            <span className="stat-card__caption">{c.caption}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function restoreFigures(pct: number) {
  const total = snapshotSize;
  const left = Math.max(1, Math.ceil((1 - pct) * RESTORE_MINUTES));
  return {
    pctText: `${Math.round(pct * 100)}%`,
    bytes: `${(total.gb * pct).toFixed(1)} of ${total.gb} GB`,
    files: `${Math.round(total.files * pct).toLocaleString("en-GB")} of ${total.files.toLocaleString("en-GB")} files`,
    left: `about ${left} min left`,
  };
}

/** A restore running with its dialog closed: a slim row in the status panel. */
function RestoreStrip({ restoring, onShow }: { restoring: NonNullable<Restoring>; onShow: () => void }) {
  const f = restoreFigures(restoring.pct);
  return (
    <div className="bk-strip" role="status">
      <span className="bk-strip__text">
        <strong>Restoring the backup from {restoring.run.when}</strong>
        <span className="bk-sub">
          {f.pctText} · {f.bytes} · {f.left}
        </span>
      </span>
      <Progress value={restoring.pct} label="Restore progress" />
      <button type="button" className="btn btn-secondary" onClick={onShow}>
        Show
      </button>
    </div>
  );
}

function NotSetUp({ onStart }: { onStart: () => void }) {
  return (
    <Panel
      id="bk-off"
      title="Backups are off"
      lede="This workspace isn't backed up yet. Set up a backup and the app saves a copy of everything in it on a schedule, while it's open."
    >
      <ul className="bk-steps bk-intro">
        <li>
          <ClockCounterClockwiseIcon size={16} />
          <span>
            <strong>Every 12 hours, or as often as you choose.</strong> Each backup only stores what changed, so it
            usually takes under a minute. Deploys, Prepare and AI runs wait while it runs.
          </span>
        </li>
        <li>
          <LockKeyIcon size={16} />
          <span>
            <strong>Encrypted with your password.</strong> Without it no backup can be opened, so keep a copy in your
            password manager.
          </span>
        </li>
        <li>
          <CloudArrowUpIcon size={16} />
          <span>
            <strong>Stored here, copied to the cloud.</strong> Backups go to a backup storage folder on this
            computer, then their new files are copied to destinations such as iCloud Drive or a NAS.
          </span>
        </li>
      </ul>
      <div className="bk-foot">
        <span className="bk-foot__note">
          Already have backups from another computer? Set up, then connect the existing backup storage folder instead
          of creating one.
        </span>
        <button type="button" className="btn btn-primary" onClick={onStart}>
          Set up backups
        </button>
      </div>
    </Panel>
  );
}

function SettingsForm({
  mode,
  initial,
  onCancel,
  onSave,
  savedNote,
}: {
  mode: "create" | "edit";
  initial: BackupSettings;
  onCancel: () => void;
  onSave: (s: BackupSettings) => void;
  savedNote: boolean;
}) {
  const [s, setS] = useState(initial);
  const [base, setBase] = useState(initial);
  const [pw, setPw] = useState("correct-horse-battery");
  const [pw2, setPw2] = useState("correct-horse-battery");
  const [show, setShow] = useState(false);
  const [stored, setStored] = useState(false);
  const set = <K extends keyof BackupSettings>(k: K, v: BackupSettings[K]) => setS((cur) => ({ ...cur, [k]: v }));

  const pwProblem = mode === "create" && (pw.length < 12 ? "Use at least 12 characters." : pw !== pw2 ? "The two passwords don't match." : null);
  const ready = mode === "edit" || (!pwProblem && stored);
  const changed = JSON.stringify(s) !== JSON.stringify(base);

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
      {savedNote && (
        <div className="bk-saved" role="status">
          <SaveStatus state="saved" text={`Saved to settings.yaml · ${everyLabel(s.intervalHours).toLowerCase()}`} />
        </div>
      )}
      <div className="bk-form">
        <div className="bk-field">
          <span className="bk-field__label">
            Backup storage folder
            <span className="bk-sub">On this computer, outside any synced folder. Every backup is stored here first.</span>
          </span>
          <div className="bk-field__control">
            {mode === "create" ? (
              <>
                <div className="bk-inline">
                  <input className="input s-mono" aria-label="Backup storage folder" value={s.repository} onChange={(e) => set("repository", e.target.value)} />
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
            <span className="bk-sub">
              After each backup, new files in the backup storage folder are copied one way into each folder. An
              unavailable one catches up at the next run.
            </span>
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
          <button
            type="button"
            className="btn btn-ghost"
            disabled={mode === "edit" && !changed}
            onClick={() => (mode === "edit" ? setS(base) : onCancel())}
          >
            {mode === "edit" ? "Discard changes" : "Cancel"}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!ready || (mode === "edit" && !changed)}
            onClick={() => {
              setBase(s);
              onSave(s);
            }}
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
  run,
  choices,
  onPick,
  onCancel,
  onRestore,
}: {
  run: BackupRun;
  choices: BackupRun[];
  onPick: (run: BackupRun) => void;
  onCancel: () => void;
  onRestore: (target: string) => void;
}) {
  const [target, setTarget] = useState(restoreTarget(run));
  useEffect(() => setTarget(restoreTarget(run)), [run]);
  const taken = target.replace(/\\+$/, "").toLowerCase() === "c:\\users\\admin\\naturally-inked-studio-workspace";

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
          <dd>
            {snapshotSize.gb} GB · {snapshotSize.files.toLocaleString("en-GB")} files
          </dd>
          <dt>Takes</dt>
          <dd>About {RESTORE_MINUTES} minutes. You can keep working while it runs.</dd>
        </dl>
        <div className="bk-field__control">
          <span className="bk-field__label">Restore into</span>
          <div className="bk-inline">
            <input className="input s-mono" aria-label="Restore into" value={target} onChange={(e) => setTarget(e.target.value)} />
            <button type="button" className="btn btn-secondary">
              <FolderOpenIcon size={16} /> Choose…
            </button>
          </div>
          {taken ? (
            <span className="adm-error-text">That's your live workspace. Choose a new, empty folder.</span>
          ) : (
            <span className="bk-sub">A new folder. A folder that already has files in it isn't accepted.</span>
          )}
        </div>
        <p className="bk-note">
          <InfoIcon size={16} />
          <span>Read from the backup storage folder on this computer. Nothing is downloaded from iCloud Drive.</span>
        </p>
        <div className="bk-dialog__foot">
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" onClick={() => onRestore(target)} disabled={taken}>
            Restore to this folder
          </button>
        </div>
      </div>
    </div>
  );
}

function RestoringDialog({
  restoring,
  onHide,
  onCancel,
}: {
  restoring: NonNullable<Restoring>;
  onHide: () => void;
  onCancel: () => void;
}) {
  const f = restoreFigures(restoring.pct);
  return (
    <div className="bk-scrim">
      <div className="bk-dialog" role="dialog" aria-modal="true" aria-labelledby="bk-restoring-title">
        <div>
          <h2 className="bk-dialog__title" id="bk-restoring-title">
            Restoring the backup from {restoring.run.when}
          </h2>
          <p className="bk-dialog__lede">
            Into <span className="s-mono">{restoring.target}</span>
          </p>
        </div>
        <div className="bk-progress" role="status" aria-live="polite">
          <div className="bk-progress__top">
            <strong className="bk-progress__pct">{f.pctText}</strong>
            <span className="bk-sub">{f.left}</span>
          </div>
          <Progress value={restoring.pct} label="Restore progress" />
          <span className="bk-sub">
            {f.bytes} · {f.files}
          </span>
        </div>
        <p className="bk-note">
          <InfoIcon size={16} />
          <span>
            You can keep working while it runs. Its progress stays on the Backup page, and scheduled backups still
            run. Closing the app stops the restore.
          </span>
        </p>
        <div className="bk-dialog__foot">
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            Stop restore
          </button>
          <button type="button" className="btn btn-primary" onClick={onHide}>
            Keep working
          </button>
        </div>
      </div>
    </div>
  );
}

function RestoredDialog({ run, target, onDone }: { run: BackupRun; target: string; onDone: () => void }) {
  return (
    <div className="bk-scrim">
      <div className="bk-dialog" role="dialog" aria-modal="true" aria-labelledby="bk-done-title">
        <span className="bk-done-icon" aria-hidden="true">
          <CheckIcon size={24} weight="bold" />
        </span>
        <div>
          <h2 className="bk-dialog__title" id="bk-done-title">
            Restored {snapshotSize.files.toLocaleString("en-GB")} files
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
          <button type="button" className="btn btn-primary" onClick={onDone}>
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
