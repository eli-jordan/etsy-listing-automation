// Restore (workspace-backup plan, PR 7; interactions, *Restore*): the
// restore dialog, the progress dialog, the strip and note in the status
// panel, and the Restored dialog. The markup is the prototype's
// (`_prototype.tsx`) without its timers: progress comes from the status poll.
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { CopyIcon } from "@phosphor-icons/react/dist/csr/Copy";
import { InfoIcon } from "@phosphor-icons/react/dist/csr/Info";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { type ReactNode, useState } from "react";
import type { BackupSnapshot, BackupSnapshots, RestoreStatus } from "../../../api/backup";
import { ago, bytes, joined, restoreFigures, restoreNote, samePath, when } from "./backupText";
import type { RestoreFlow } from "./useRestore";
import { BackupDialog } from "./BackupDialog";

export function Progress({ value, label }: { value: number; label: string }) {
  return (
    <span
      className="bk-bar"
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(value * 100)}
    >
      <span className="bk-bar__fill" style={{ width: `${Math.max(2, value * 100)}%` }} />
    </span>
  );
}

function RestoreDialog({
  choices,
  initial,
  now,
  onCancel,
  onRestore,
}: {
  choices: BackupSnapshots;
  initial: string | undefined;
  now: number;
  onCancel: () => void;
  /** Starts the restore; a refusal's message, or null once it has started. */
  onRestore: (snapshot: string, target: string) => Promise<string | null>;
}) {
  const pick = (id: string | undefined) =>
    choices.snapshots.find((s) => s.id === id) ?? choices.snapshots[0];
  const [snapshot, setSnapshot] = useState(() => pick(initial));
  const [target, setTarget] = useState(() => (snapshot ? snapshot.restore_target : ""));
  const [refusal, setRefusal] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const taken = samePath(target, choices.workspace);

  const choose = (next: BackupSnapshot | undefined) => {
    if (!next) return;
    setSnapshot(next);
    setTarget(next.restore_target);
    setRefusal(null);
  };
  let hint = (
    <span className="bk-sub">
      A new folder. A folder that already has files in it isn't accepted.
    </span>
  );
  if (taken)
    hint = (
      <span className="adm-error-text">
        That's your live workspace. Choose a new, empty folder.
      </span>
    );
  else if (refusal)
    hint = (
      <span className="adm-error-text" role="alert">
        {refusal}
      </span>
    );
  const submit = async () => {
    if (!snapshot) return;
    setStarting(true);
    setRefusal(await onRestore(snapshot.id, target.trim()));
    setStarting(false);
  };

  return (
    <BackupDialog labelledBy="bk-restore-title" onDismiss={onCancel}>
      <div>
        <h2 className="bk-dialog__title" id="bk-restore-title">
          Restore the backup from {snapshot ? when(snapshot.time) : "…"}
        </h2>
        <p className="bk-dialog__lede">
          The whole workspace as it was then, written into a new folder. Your current workspace
          isn't changed.
        </p>
      </div>
      <dl className="bk-facts">
        <dt>Backup</dt>
        <dd>
          <select
            className="bk-pick"
            aria-label="Backup to restore"
            value={snapshot?.id}
            onChange={(e) => choose(pick(e.target.value))}
          >
            {choices.snapshots.map((s) => (
              <option key={s.id} value={s.id}>
                {when(s.time)} ({ago(s.time, now)})
              </option>
            ))}
          </select>
        </dd>
        <dt>Size</dt>
        <dd>
          {bytes(snapshot?.size)} · {snapshot?.files?.toLocaleString("en-GB") ?? "—"} files
        </dd>
        <dt>Takes</dt>
        {/* No estimate before it starts: the time left shows once restic reports a rate. */}
        <dd>A few minutes for a whole workspace. You can keep working while it runs.</dd>
      </dl>
      <div className="bk-field__control">
        <span className="bk-field__label">Restore into</span>
        <input
          className="input s-mono"
          aria-label="Restore into"
          value={target}
          onChange={(e) => {
            setTarget(e.target.value);
            setRefusal(null);
          }}
        />
        {hint}
      </div>
      <p className="bk-note">
        <InfoIcon size={16} />
        <span>Read from the backup storage folder on this computer. Nothing is downloaded.</span>
      </p>
      <div className="bk-dialog__foot">
        <button type="button" className="btn btn-ghost" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => void submit()}
          disabled={taken || !snapshot || !target.trim() || starting}
        >
          Restore to this folder
        </button>
      </div>
    </BackupDialog>
  );
}

function RestoringDialog({
  restore,
  onHide,
  onStop,
}: {
  restore: RestoreStatus;
  onHide: () => void;
  onStop: () => void;
}) {
  const f = restoreFigures(restore);
  return (
    <BackupDialog labelledBy="bk-restoring-title" onDismiss={onHide}>
      <div>
        <h2 className="bk-dialog__title" id="bk-restoring-title">
          Restoring the backup from {when(restore.snapshot_time)}
        </h2>
        <p className="bk-dialog__lede">
          Into <span className="s-mono">{restore.target}</span>
        </p>
      </div>
      <div className="bk-progress" role="status" aria-live="polite">
        <div className="bk-progress__top">
          <strong className="bk-progress__pct">{f.pctText}</strong>
          <span className="bk-sub">{f.left}</span>
        </div>
        <Progress value={restore.percent} label="Restore progress" />
        <span className="bk-sub">{joined(f.bytes, f.files)}</span>
      </div>
      <p className="bk-note">
        <InfoIcon size={16} />
        <span>
          You can keep working while it runs. Its progress stays on the Backup page, and scheduled
          backups still run. Closing the app stops the restore.
        </span>
      </p>
      <div className="bk-dialog__foot">
        <button type="button" className="btn btn-ghost" onClick={onStop}>
          Stop restore
        </button>
        <button type="button" className="btn btn-primary" onClick={onHide}>
          Keep working
        </button>
      </div>
    </BackupDialog>
  );
}

function RestoredDialog({ restore, onDone }: { restore: RestoreStatus; onDone: () => void }) {
  const files = restore.files_done ?? restore.files_total;
  return (
    <BackupDialog labelledBy="bk-done-title" onDismiss={onDone}>
      <span className="bk-done-icon" aria-hidden="true">
        <CheckIcon size={24} weight="bold" />
      </span>
      <div>
        <h2 className="bk-dialog__title" id="bk-done-title">
          {files == null ? "Restored" : `Restored ${files.toLocaleString("en-GB")} files`}
        </h2>
        <p className="bk-dialog__lede">
          The workspace from {when(restore.snapshot_time)} is in this folder:
        </p>
      </div>
      <div className="bk-inline">
        <input
          className="input s-mono"
          aria-label="Restored folder"
          readOnly
          value={restore.target}
        />
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => void navigator.clipboard?.writeText(restore.target)}
        >
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
            Or switch the app to it: set <code className="s-mono">ETSY_LISTINGS_ROOT</code> to this
            folder and restart the app.
          </li>
        </ol>
      </div>
      <div className="bk-dialog__foot">
        <button type="button" className="btn btn-primary" onClick={onDone}>
          Done
        </button>
      </div>
    </BackupDialog>
  );
}

function Strip({ children, actions }: { children: ReactNode; actions: ReactNode }) {
  return (
    <div className="bk-strip" role="status">
      <span className="bk-strip__text">{children}</span>
      {actions}
    </div>
  );
}

/** The restore in the status panel: its progress while the dialog is
 * closed, then a note once it has ended. */
export function RestoreStrip({ flow }: { flow: RestoreFlow }) {
  const { restore } = flow;
  if (!restore || (flow.shown && restore.outcome !== "failed" && restore.outcome !== "stopped"))
    return null;
  if (restore.outcome === "running") {
    const f = restoreFigures(restore);
    return (
      <Strip
        actions={
          <>
            <Progress value={restore.percent} label="Restore progress" />
            <button type="button" className="btn btn-secondary" onClick={flow.show}>
              Show
            </button>
          </>
        }
      >
        <strong>Restoring the backup from {when(restore.snapshot_time)}</strong>
        <span className="bk-sub">{joined(f.pctText, f.bytes, f.left)}</span>
      </Strip>
    );
  }
  const done = restore.outcome === "succeeded";
  return (
    <Strip
      actions={
        <>
          {done && (
            <button type="button" className="btn btn-secondary" onClick={flow.show}>
              Show
            </button>
          )}
          <button
            type="button"
            className="btn btn-ghost"
            aria-label="Dismiss"
            onClick={() => flow.dismiss(restore)}
          >
            <XIcon size={16} />
          </button>
        </>
      }
    >
      <strong>{restoreNote(restore)}</strong>
      {done && <span className="s-mono bk-sub">{restore.target}</span>}
    </Strip>
  );
}

/** Whichever restore dialog is open. */
export function RestoreDialogs({ flow, now }: { flow: RestoreFlow; now: number }) {
  const { restore, picking } = flow;
  return (
    <>
      {picking && (
        <RestoreDialog
          choices={picking.choices}
          initial={picking.snapshot}
          now={now}
          onCancel={flow.cancel}
          onRestore={flow.start}
        />
      )}
      {flow.shown && restore?.outcome === "running" && (
        <RestoringDialog restore={restore} onHide={flow.hide} onStop={flow.stop} />
      )}
      {flow.shown && restore?.outcome === "succeeded" && (
        <RestoredDialog restore={restore} onDone={() => flow.dismiss(restore)} />
      )}
    </>
  );
}
