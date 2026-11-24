// The Backup section's panels, from the approved `workspace-backup` mockup
// (`design/scenes/workspace-backup/_parts.tsx` and `_prototype.tsx`), fed by
// `GET /api/backup` and its history instead of fixtures.
import { ArrowCounterClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowCounterClockwise";
import { ArrowRightIcon } from "@phosphor-icons/react/dist/csr/ArrowRight";
import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { CircleNotchIcon } from "@phosphor-icons/react/dist/csr/CircleNotch";
import { ClockCounterClockwiseIcon } from "@phosphor-icons/react/dist/csr/ClockCounterClockwise";
import { CloudArrowUpIcon } from "@phosphor-icons/react/dist/csr/CloudArrowUp";
import { FolderIcon } from "@phosphor-icons/react/dist/csr/Folder";
import { HardDrivesIcon } from "@phosphor-icons/react/dist/csr/HardDrives";
import { LockKeyIcon } from "@phosphor-icons/react/dist/csr/LockKey";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { XCircleIcon } from "@phosphor-icons/react/dist/csr/XCircle";
import type { ReactNode } from "react";
import type {
  BackupStatus,
  DestinationStatus,
  HistoryEntry,
  RetentionSettings,
} from "../../../api/backup";
import type { BackupsOn, Copy } from "../../../shell/backupAttention";
import {
  ago,
  bytes,
  duration,
  everyLabel,
  lastPart,
  type RowResult,
  rowResult,
  when,
} from "./backupText";

export function Panel({
  id,
  title,
  lede,
  aside,
  children,
}: {
  id: string;
  title: string;
  lede?: ReactNode;
  aside?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section className="b-panel" aria-labelledby={id}>
      <div className="b-panel__head">
        <div>
          <h2 className="b-panel__title" id={id}>
            {title}
          </h2>
          {lede && <p className="b-panel__lede">{lede}</p>}
        </div>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function Pill({
  tone,
  children,
}: {
  tone: "ok" | "warn" | "bad" | "quiet";
  children: ReactNode;
}) {
  return <span className={`bk-pill bk-pill--${tone}`}>{children}</span>;
}

export function NotSetUp({ onStart }: { onStart: () => void }) {
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
            <strong>Every 12 hours, or as often as you choose.</strong> Each backup only stores what
            changed, so it usually takes under a minute. Deploys, Prepare and AI runs wait while it
            runs.
          </span>
        </li>
        <li>
          <LockKeyIcon size={16} />
          <span>
            <strong>Encrypted with your password.</strong> Without it no backup can be opened, so
            keep a copy in your password manager.
          </span>
        </li>
        <li>
          <CloudArrowUpIcon size={16} />
          <span>
            <strong>Stored here, copied to the cloud.</strong> Backups go to a backup storage folder
            on this computer, then their new files are copied to destinations such as iCloud Drive
            or a NAS.
          </span>
        </li>
      </ul>
      <div className="bk-foot">
        <span className="bk-foot__note">
          Already have backups from another computer? Add the folder that holds them as a
          destination, and set-up connects them instead of starting new ones.
        </span>
        <button type="button" className="btn btn-primary" onClick={onStart}>
          Set up backups
        </button>
      </div>
    </Panel>
  );
}

/** The one-line health summary at the top of the section. */
export function StatusPanel({
  tone,
  headline,
  detail,
  running,
  runningLine,
  restore,
  onBackup,
  children,
}: {
  tone: "ok" | "warn";
  headline: string;
  detail: string;
  /** A backup or repair runs, so Back up now waits. */
  running: boolean;
  /** What it is doing, under the detail. */
  runningLine: string | undefined;
  /** Restore…: disabled while a restore runs or with no backup to restore. */
  restore: { disabled: boolean; onClick: () => void };
  onBackup: () => void;
  /** A restore in progress or its note. */
  children?: ReactNode;
}) {
  return (
    <section className={`b-panel bk-status bk-status--${tone}`} aria-labelledby="bk-status">
      <span className="bk-status__icon" aria-hidden="true">
        {tone === "ok" ? (
          <CheckCircleIcon size={26} weight="fill" />
        ) : (
          <WarningIcon size={26} weight="fill" />
        )}
      </span>
      <div className="bk-status__text">
        <h2 className="b-panel__title" id="bk-status">
          {headline}
        </h2>
        <p className="b-panel__lede">{detail}</p>
        {runningLine && (
          <p className="bk-status__running" role="status">
            <CircleNotchIcon size={14} className="adm-spin" /> {runningLine}
          </p>
        )}
      </div>
      <div className="bk-status__actions">
        <button
          type="button"
          className="btn btn-secondary"
          disabled={restore.disabled}
          onClick={restore.onClick}
        >
          <ArrowCounterClockwiseIcon size={16} /> Restore…
        </button>
        <button type="button" className="btn btn-primary" disabled={running} onClick={onBackup}>
          {running ? "Backing up…" : "Back up now"}
        </button>
      </div>
      {children && <div className="bk-status__extra">{children}</div>}
    </section>
  );
}

function repositoryState(status: BackupStatus): { ok: boolean; text: string } {
  const repository = status.repository;
  if (!repository || repository.missing) return { ok: false, text: "Not found" };
  if (repository.problem) return { ok: false, text: "Can't be read" };
  const check = repository.last_check;
  if (check && !check.ok) return { ok: false, text: "Check failed" };
  return { ok: true, text: check ? `Checked ${when(check.at).split(",")[0]}` : "Not checked yet" };
}

function copyState({ destination, toCheck: found }: Copy): { ok: boolean; text: string } {
  if (found) return { ok: false, text: `${found} file${found === 1 ? "" : "s"} to check` };
  if (destination.short_problem) return { ok: false, text: destination.short_problem };
  if (destination.behind) return { ok: false, text: "Behind" };
  return { ok: true, text: "Up to date" };
}

/**
 * Where the data lives, as the three places it passes through: the app
 * backs up the workspace into the backup storage folder, then copies new
 * files one way into each destination, and the sync client takes it there.
 */
export function StoragePipeline({
  view,
  now,
  onSetup,
}: {
  view: BackupsOn;
  now: number;
  onSetup: () => void;
}) {
  const { status } = view;
  const repository = status.repository?.path ?? "";
  const stored = repositoryState(status);
  const every = everyLabel(status.interval_hours ?? 12);
  return (
    <Panel
      id="bk-where"
      title="Where your backups are"
      lede="Two steps after every backup. Nothing here ever edits or replaces a file in a destination, so iCloud has nothing to rename."
      aside={
        <button type="button" className="btn btn-secondary" onClick={onSetup}>
          Edit setup
        </button>
      }
    >
      <ol className="bk-flow">
        <li className="bk-node">
          <span className="bk-node__head">
            <FolderIcon size={18} /> Workspace
          </span>
          <span className="bk-sub">The files the app works on.</span>
        </li>
        <li className="bk-arrow" aria-label={`Step 1: back up, ${every.toLowerCase()}`}>
          <span className="bk-arrow__step">1</span>
          <span className="bk-arrow__text">
            <strong>Back up</strong>
            <span>{every}. Only changes are stored, encrypted.</span>
          </span>
          <ArrowRightIcon size={18} className="bk-arrow__icon" />
        </li>
        <li className="bk-node">
          <span className="bk-node__head">
            <HardDrivesIcon size={18} /> Backup storage folder
          </span>
          <span className="s-mono bk-node__path" title={repository}>
            {lastPart(repository)}
          </span>
          <span className="bk-sub">
            {status.repository?.snapshots ?? 0} backups. On this computer. Restores read from here.
          </span>
          <Pill tone={stored.ok ? "ok" : "bad"}>{stored.text}</Pill>
        </li>
        <li className="bk-arrow" aria-label="Step 2: copy new files one way">
          <span className="bk-arrow__step">2</span>
          <span className="bk-arrow__text">
            <strong>Copy</strong>
            <span>New files only, one way. Removed when they expire.</span>
          </span>
          <ArrowRightIcon size={18} className="bk-arrow__icon" />
        </li>
        <li className="bk-dests">
          {view.copies.length === 0 && (
            <span className="bk-node bk-node--empty bk-sub">
              No destinations. A failed disk loses the backups too.
            </span>
          )}
          {view.copies.map((copy) => {
            const d = copy.destination;
            const state = copyState(copy);
            return (
              <span className="bk-node" key={d.path}>
                <span className="bk-node__head">
                  <CloudArrowUpIcon size={18} /> {d.name}
                </span>
                <span className="s-mono bk-node__path" title={d.path}>
                  {lastPart(d.path)}
                </span>
                <span className="bk-sub">
                  Copied {d.last_copy ? ago(d.last_copy, now) : "never"}.{" "}
                  {d.icloud ? "iCloud for Windows uploads it from here." : "A complete copy."}
                </span>
                <Pill tone={state.ok ? "ok" : "warn"}>{state.text}</Pill>
              </span>
            );
          })}
        </li>
      </ol>
    </Panel>
  );
}

const RESULT: Record<RowResult, { label: string; tone: "ok" | "warn" | "bad"; icon: ReactNode }> = {
  ok: { label: "Backed up", tone: "ok", icon: <CheckCircleIcon size={16} weight="fill" /> },
  partial: { label: "Not copied", tone: "warn", icon: <WarningIcon size={16} weight="fill" /> },
  stopped: { label: "Stopped", tone: "warn", icon: <WarningIcon size={16} weight="fill" /> },
  failed: { label: "Failed", tone: "bad", icon: <XCircleIcon size={16} weight="fill" /> },
};

const KEPT = { recent: "Recent", weekly: "Weekly", monthly: "Monthly" } as const;

/** Every run, newest first, failures included. */
export function History({
  entries,
  retention,
  fresh,
  now,
  restoreBusy,
  onRestore,
}: {
  entries: HistoryEntry[];
  retention: RetentionSettings;
  /** The run that just finished, briefly highlighted. */
  fresh: string | undefined;
  now: number;
  restoreBusy: boolean;
  onRestore: (snapshot: string) => void;
}) {
  return (
    <Panel
      id="bk-history"
      title="Backup history"
      lede={`Every backup from the last ${retention.keep_within_days} days, then the latest of each week for ${retention.weekly} weeks and of each month for ${retention.monthly} months.`}
    >
      <table className="bk-table">
        <colgroup>
          <col className="bk-c-when" />
          <col />
          <col className="bk-c-num" />
          <col className="bk-c-kept" />
          <col className="bk-c-act" />
        </colgroup>
        <thead>
          <tr>
            <th scope="col">When</th>
            <th scope="col">Result</th>
            <th scope="col" className="bk-num">
              Added
            </th>
            <th scope="col">Kept as</th>
            <th scope="col" aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => {
            const { run } = entry;
            const { result, detail } = rowResult(entry);
            const r = RESULT[result];
            const fade = run.started_at === fresh ? " bk-run--fresh" : "";
            return (
              <tr key={run.started_at} className={`bk-run bk-run--${result}${fade}`}>
                <td>
                  <span className="bk-when">{when(run.started_at)}</span>
                  <span className="bk-sub">
                    {ago(run.started_at, now)} · took {duration(run.started_at, run.finished_at)}
                  </span>
                </td>
                <td>
                  <span className={`bk-result bk-result--${r.tone}`}>
                    {r.icon} {r.label}
                  </span>
                  <span className="bk-sub bk-detail">{detail}</span>
                </td>
                <td className="bk-num">{bytes(run.data_added)}</td>
                <td>
                  {entry.kept_as ? (
                    <Pill tone="quiet">{KEPT[entry.kept_as]}</Pill>
                  ) : (
                    <span className="bk-sub">
                      {run.snapshot_id ? "No longer kept" : "Nothing saved"}
                    </span>
                  )}
                </td>
                <td className="bk-actions">
                  {entry.kept_as && run.snapshot_id && (
                    <button
                      type="button"
                      className="btn btn-ghost bk-restore"
                      disabled={restoreBusy}
                      onClick={() => onRestore(run.snapshot_id ?? "")}
                    >
                      Restore…
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {entries.length === 0 && <p className="bk-sub">No backups yet.</p>}
    </Panel>
  );
}

/** What the copy found in a destination, with the one way to fix it. */
export function ChangedFilesBanner({
  destination,
  onRepair,
}: {
  destination: DestinationStatus;
  onRepair: () => void;
}) {
  const { name } = destination;
  return (
    <div className="adm-warn bk-banner bk-changed" role="alert">
      <WarningIcon size={18} />
      <div className="bk-changed__body">
        <span>
          <strong>Files in the {name} copy changed after they were copied.</strong> restic never
          changes a file once written, so iCloud, another program or a person did. Copying to {name}{" "}
          has stopped, and nothing there was overwritten.
        </span>
        <ul className="bk-changed__list">
          {destination.changed.map((f) => (
            <li key={f.name}>
              <span className="s-mono">{f.name}</span>
              <Pill tone="warn">Changed</Pill>
              <span className="bk-changed__why">
                {bytes(f.expected_size)} when copied, {bytes(f.actual_size)} now
              </span>
            </li>
          ))}
          {destination.unexpected.map((file) => (
            <li key={file}>
              <span className="s-mono">{file}</span>
              <Pill tone="warn">Unexpected</Pill>
              <span className="bk-changed__why">
                Not a name restic writes. Probably an iCloud conflict copy.
              </span>
            </li>
          ))}
        </ul>
        <div>
          <button type="button" className="btn btn-secondary" onClick={onRepair}>
            Repair the {name} copy…
          </button>
        </div>
      </div>
    </div>
  );
}

export function RepairDialog({
  destination,
  working,
  error,
  onCancel,
  onRepair,
}: {
  destination: DestinationStatus;
  working: boolean;
  error: string | null;
  onCancel: () => void;
  onRepair: () => void;
}) {
  const { name } = destination;
  const count = destination.changed.length + destination.unexpected.length;
  return (
    <div className="bk-scrim">
      <div className="bk-dialog" role="dialog" aria-modal="true" aria-labelledby="bk-repair-title">
        <div>
          <h2 className="bk-dialog__title" id="bk-repair-title">
            Repair the {name} copy
          </h2>
          <p className="bk-dialog__lede">
            The {count} file{count === 1 ? "" : "s"} move out of the copy into a folder beside it,
            so you can look at them. Nothing is deleted. Then the copy runs again from the backup
            storage folder on this computer.
          </p>
        </div>
        <dl className="bk-facts">
          <dt>Set aside in</dt>
          <dd className="s-mono">{lastPart(destination.set_aside ?? "")}</dd>
          <dt>Copied again</dt>
          <dd>
            {destination.changed.length} file{destination.changed.length === 1 ? "" : "s"},{" "}
            {bytes(destination.changed.reduce((sum, f) => sum + f.expected_size, 0))}
          </dd>
        </dl>
        {working && (
          <p className="bk-status__running" role="status">
            <CircleNotchIcon size={14} className="adm-spin" /> Setting files aside and copying…
          </p>
        )}
        {error && (
          <p className="adm-error-text" role="alert">
            {error}
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
