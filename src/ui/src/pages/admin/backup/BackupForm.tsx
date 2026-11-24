// Set up and Setup, one form (workspace-backup interactions, *Set up and
// Setup*), from the mockup's `SettingsForm` in `_prototype.tsx`.
import { CloudArrowUpIcon } from "@phosphor-icons/react/dist/csr/CloudArrowUp";
import { EyeIcon } from "@phosphor-icons/react/dist/csr/Eye";
import { EyeSlashIcon } from "@phosphor-icons/react/dist/csr/EyeSlash";
import { HardDrivesIcon } from "@phosphor-icons/react/dist/csr/HardDrives";
import { LockKeyIcon } from "@phosphor-icons/react/dist/csr/LockKey";
import { PlusIcon } from "@phosphor-icons/react/dist/csr/Plus";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { type ReactNode, useEffect, useState } from "react";
import type { BackupStatus, IntervalHours, RetentionSettings } from "../../../api/backup";
import { Panel } from "./BackupPanels";
import {
  type BackupAnswers,
  everyLabel,
  INTERVALS,
  intervalChoice,
  intervalHint,
  type Password,
  nameOf,
  passwordProblem,
} from "./backupText";

/** A failure to show under the form, or null once it worked. */
export type Answer = Promise<string | null>;

const SAVED_NOTE_MS = 4000;

type Row = { id: number; path: string };
let nextRow = 0;
const rows = (paths: string[]): Row[] => paths.map((path) => ({ id: nextRow++, path }));

export function BackupForm({
  mode,
  initial,
  status,
  onCancel,
  onCreate,
  onSave,
}: {
  mode: "create" | "edit";
  initial: BackupAnswers;
  /** The server's status: its names for saved destinations and the
   * shortest password it accepts. */
  status: BackupStatus;
  onCancel?: () => void;
  onCreate?: (answers: BackupAnswers, password: string) => Answer;
  onSave?: (answers: BackupAnswers, base: BackupAnswers) => Answer;
}) {
  const [base, setBase] = useState(initial);
  const [s, setS] = useState(initial);
  const [destinations, setDestinations] = useState<Row[]>(() => rows(initial.destinations));
  const [password, setPassword] = useState<Password>({ pw: "", pw2: "", stored: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedNote, setSavedNote] = useState<string | null>(null);

  useEffect(() => {
    if (!savedNote) return;
    const timer = setTimeout(() => setSavedNote(null), SAVED_NOTE_MS);
    return () => clearTimeout(timer);
  }, [savedNote]);

  const answers: BackupAnswers = { ...s, destinations: destinations.map((d) => d.path) };
  const create = mode === "create";
  const changed = JSON.stringify(answers) !== JSON.stringify(base);
  const minLength = status.password_min_length;
  const ready = create ? createReady(answers, password, minLength) : changed;

  const submit = async () => {
    setBusy(true);
    setError(null);
    const failure = create ? await onCreate?.(answers, password.pw) : await onSave?.(answers, base);
    setBusy(false);
    if (failure) return setError(failure);
    if (create) return;
    setBase(answers);
    setSavedNote(`Saved to settings.yaml · ${everyLabel(answers.interval_hours).toLowerCase()}`);
  };
  const discard = () => {
    setS(base);
    setDestinations(rows(base.destinations));
    setError(null);
  };

  return (
    <Panel
      id="bk-setup"
      title={create ? "Set up backups" : "Backup settings"}
      lede="Saved to the backup block in settings.yaml. The password goes in the workspace's .env file, never in settings.yaml."
    >
      {savedNote && (
        <div className="bk-saved adm-save adm-save--ok" role="status">
          {savedNote}
        </div>
      )}
      <div className="bk-form">
        <Field
          label="Backup storage folder"
          hint="On this computer, outside any synced folder. Every backup is stored here first."
        >
          <StorageFolder
            create={create}
            value={s.repository}
            onChange={(repository) => setS({ ...s, repository })}
          />
        </Field>
        <Field
          label="Back up every"
          hint="Counted from the last backup that succeeded, and checked when the app starts."
        >
          <Interval value={s.interval_hours} onChange={(h) => setS({ ...s, interval_hours: h })} />
        </Field>
        <Field
          label="Password"
          hint="Encrypts every backup. Saved as ETSY_LISTINGS_BACKUP_PASSWORD in .env."
        >
          {create ? (
            <PasswordFields value={password} minLength={minLength} onChange={setPassword} />
          ) : (
            <span className="bk-readonly">
              <LockKeyIcon size={16} /> Set, in .env
            </span>
          )}
        </Field>
        <Field
          label="Copy to"
          hint="After each backup, new files in the backup storage folder are copied one way into each folder. An unavailable one catches up at the next run."
        >
          <Destinations
            value={destinations}
            nameOf={(path) => nameOf(status, path)}
            onChange={setDestinations}
          />
        </Field>
        <Field label="Keep" hint="Older backups are removed once a week.">
          <Keep
            value={s.retention}
            onChange={(retention) => setS((cur) => ({ ...cur, retention }))}
          />
        </Field>
        {error && (
          <p className="adm-error-text" role="alert">
            {error}
          </p>
        )}
        <div className="bk-foot">
          {create && (
            <span className="bk-foot__note">
              The first backup copies the whole workspace and can take 20 minutes or more. Jobs you
              start meanwhile wait until it finishes.
            </span>
          )}
          <button
            type="button"
            className="btn btn-ghost"
            disabled={busy || (!create && !changed)}
            onClick={create ? onCancel : discard}
          >
            {create ? "Cancel" : "Discard changes"}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy || !ready}
            onClick={() => void submit()}
          >
            {create ? "Create and back up now" : "Save"}
          </button>
        </div>
      </div>
    </Panel>
  );
}

function createReady(answers: BackupAnswers, password: Password, minLength: number): boolean {
  return (
    passwordProblem(password, minLength) === null &&
    password.stored &&
    answers.repository.trim() !== ""
  );
}

function Field({ label, hint, children }: { label: string; hint: string; children: ReactNode }) {
  return (
    <div className="bk-field">
      <span className="bk-field__label">
        {label}
        <span className="bk-sub">{hint}</span>
      </span>
      <div className="bk-field__control">{children}</div>
    </div>
  );
}

function StorageFolder({
  create,
  value,
  onChange,
}: {
  create: boolean;
  value: string;
  onChange: (value: string) => void;
}) {
  if (!create)
    return (
      <>
        <span className="bk-readonly">
          <HardDrivesIcon size={16} /> <span className="s-mono">{value}</span>
        </span>
        <span className="bk-sub">
          Moving it starts a new backup history, so it can&apos;t be changed here.
        </span>
      </>
    );
  return (
    <>
      <input
        className="input s-mono"
        aria-label="Backup storage folder"
        placeholder="C:\Users\you\shop-backups"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      <span className="bk-sub">An empty or new folder.</span>
    </>
  );
}

function Interval({
  value,
  onChange,
}: {
  value: IntervalHours;
  onChange: (value: IntervalHours) => void;
}) {
  return (
    <>
      <div className="seg bk-seg" role="radiogroup" aria-label="Back up every">
        {INTERVALS.map((h) => (
          <button
            key={h}
            type="button"
            role="radio"
            aria-checked={value === h}
            className={value === h ? "seg-opt seg-opt--on" : "seg-opt"}
            onClick={() => onChange(h)}
          >
            {intervalChoice(h)}
          </button>
        ))}
      </div>
      <span className="bk-sub">{intervalHint(value)}</span>
    </>
  );
}

export function PasswordFields({
  value,
  minLength,
  onChange,
}: {
  value: Password;
  minLength: number;
  onChange: (value: Password) => void;
}) {
  const [show, setShow] = useState(false);
  const problem = passwordProblem(value, minLength);
  const type = show ? "text" : "password";
  return (
    <>
      <div className="bk-inline bk-pw">
        <input
          className="input"
          type={type}
          aria-label="Password"
          placeholder="Password"
          value={value.pw}
          onChange={(e) => onChange({ ...value, pw: e.target.value })}
        />
        <input
          className="input"
          type={type}
          aria-label="Repeat password"
          placeholder="Repeat password"
          value={value.pw2}
          onChange={(e) => onChange({ ...value, pw2: e.target.value })}
        />
        <button
          type="button"
          className="btn btn-secondary"
          aria-pressed={show}
          onClick={() => setShow(!show)}
        >
          {show ? <EyeSlashIcon size={16} /> : <EyeIcon size={16} />} {show ? "Hide" : "Show"}
        </button>
      </div>
      {value.pw !== "" && problem && <span className="adm-error-text">{problem}</span>}
      <label className="bk-check">
        <input
          type="checkbox"
          checked={value.stored}
          onChange={(e) => onChange({ ...value, stored: e.target.checked })}
        />
        <span>
          I&apos;ve saved this password in my password manager. A backup restored to a new computer
          can&apos;t be opened without it, because the copy of .env inside the backup is encrypted
          too.
        </span>
      </label>
    </>
  );
}

function Destinations({
  value,
  nameOf,
  onChange,
}: {
  value: Row[];
  nameOf: (path: string) => string;
  onChange: (value: Row[]) => void;
}) {
  return (
    <>
      {value.length > 0 && (
        <div className="sa-table">
          {value.map((d, index) => (
            <div className="sa-row bk-dest bk-dest--edit" key={d.id}>
              <CloudArrowUpIcon size={18} />
              <span className="sa-row__label">{nameOf(d.path)}</span>
              <input
                className="input s-mono"
                aria-label={`Destination ${index + 1} folder`}
                value={d.path}
                onChange={(e) =>
                  onChange(value.map((x) => (x.id === d.id ? { ...x, path: e.target.value } : x)))
                }
              />
              <button
                type="button"
                className="btn btn-ghost"
                aria-label={`Remove destination ${index + 1}`}
                onClick={() => onChange(value.filter((x) => x.id !== d.id))}
              >
                <XIcon size={16} />
              </button>
            </div>
          ))}
        </div>
      )}
      {value.length === 0 && (
        <span className="bk-sub">
          No destinations. Backups stay on this computer only, so a failed disk loses them too.
        </span>
      )}
      <div>
        <button
          type="button"
          className="btn btn-secondary bk-add"
          onClick={() => onChange([...value, ...rows([""])])}
        >
          <PlusIcon size={16} /> Add destination
        </button>
      </div>
    </>
  );
}

function Keep({
  value,
  onChange,
}: {
  value: RetentionSettings;
  onChange: (value: RetentionSettings) => void;
}) {
  const set = (key: keyof RetentionSettings) => (n: number) => onChange({ ...value, [key]: n });
  return (
    <div className="bk-keep">
      <Num
        label="days of every backup"
        value={value.keep_within_days}
        onChange={set("keep_within_days")}
      />
      <Num label="weeks, latest each week" value={value.weekly} onChange={set("weekly")} />
      <Num label="months, latest each month" value={value.monthly} onChange={set("monthly")} />
    </div>
  );
}

/** Digits only; zero and empty are refused, keeping the last good number. */
function Num({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
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
