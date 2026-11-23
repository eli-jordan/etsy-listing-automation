// The missing-repository banner and its two actions (workspace-backup spec,
// *Missing repository*; plan, PR 8). Never mocked: the interactions doc's
// *Warnings* table names the actions, and the dialog follows the repair and
// restore dialogs' layout.
import { CircleNotchIcon } from "@phosphor-icons/react/dist/csr/CircleNotch";
import { InfoIcon } from "@phosphor-icons/react/dist/csr/Info";
import { LockKeyIcon } from "@phosphor-icons/react/dist/csr/LockKey";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { useState } from "react";
import type { BackupWarning } from "../../../api/backup";
import type { RepositoryAction } from "../useWorkspaceSettings";
import { PasswordFields } from "./BackupForm";
import { type Password, passwordProblem } from "./backupText";

export type RepositoryMode = RepositoryAction["kind"];

export function MissingRepositoryBanner({
  warning,
  onAction,
}: {
  warning: BackupWarning;
  onAction: (mode: RepositoryMode) => void;
}) {
  return (
    <div className="adm-warn bk-banner" role="alert">
      <WarningIcon size={18} />
      <span>
        <strong>{warning.message}</strong> Create a new, empty repository, or connect one you
        already have, such as a copy in iCloud Drive.
      </span>
      <button
        type="button"
        className="btn btn-secondary bk-banner__btn"
        onClick={() => onAction("create")}
      >
        Create a new repository
      </button>
      <button
        type="button"
        className="btn btn-secondary bk-banner__btn"
        onClick={() => onAction("connect")}
      >
        Connect an existing repository
      </button>
    </div>
  );
}

const TEXT = {
  create: {
    title: "Create a new backup repository",
    lede: "An empty repository for new backups. The next backup is a full one, and existing copies in your destinations are reported as changed until you repair them.",
    folder: "New backup storage folder",
    submit: "Create and back up now",
    working: "Creating the repository…",
  },
  connect: {
    title: "Connect an existing repository",
    lede: "The repository is copied to this computer first, so the folder you copy from is only read. A whole repository can take a while to copy.",
    folder: "Copy into",
    submit: "Copy and connect",
    working: "Copying the repository to this computer…",
  },
} as const;

/** Create or connect. `onSubmit` answers with a refusal's message, or null
 * once the repository is there. */
export function RepositoryDialog({
  mode,
  repository,
  passwordStored,
  onCancel,
  onSubmit,
}: {
  mode: RepositoryMode;
  repository: string;
  passwordStored: boolean;
  onCancel: () => void;
  onSubmit: (action: RepositoryAction) => Promise<string | null>;
}) {
  const text = TEXT[mode];
  const [folder, setFolder] = useState(repository);
  const [source, setSource] = useState("");
  const [password, setPassword] = useState<Password>({ pw: "", pw2: "", stored: false });
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const edit =
    <T,>(set: (value: T) => void) =>
    (value: T) => {
      set(value);
      setError(null);
    };

  const given = passwordStored ? null : password.pw;
  let ready = folder.trim() !== "";
  if (mode === "connect") ready &&= source.trim() !== "" && (passwordStored || password.pw !== "");
  else ready &&= passwordStored || (passwordProblem(password) === null && password.stored);

  const submit = async () => {
    setWorking(true);
    setError(null);
    const action: RepositoryAction =
      mode === "create"
        ? { kind: "create", body: { repository: folder.trim(), password: given } }
        : {
            kind: "connect",
            body: { source: source.trim(), repository: folder.trim(), password: given },
          };
    const refused = await onSubmit(action);
    setWorking(false);
    setError(refused);
  };

  return (
    <div className="bk-scrim">
      <div className="bk-dialog" role="dialog" aria-modal="true" aria-labelledby="bk-repo-title">
        <div>
          <h2 className="bk-dialog__title" id="bk-repo-title">
            {text.title}
          </h2>
          <p className="bk-dialog__lede">{text.lede}</p>
        </div>
        {mode === "connect" && (
          <div className="bk-field__control">
            <span className="bk-field__label">Copy from</span>
            <input
              className="input s-mono"
              aria-label="Copy from"
              placeholder="The folder that holds config, data, index, keys and snapshots"
              value={source}
              onChange={(e) => edit(setSource)(e.target.value)}
            />
          </div>
        )}
        <div className="bk-field__control">
          <span className="bk-field__label">{text.folder}</span>
          <input
            className="input s-mono"
            aria-label={text.folder}
            value={folder}
            onChange={(e) => edit(setFolder)(e.target.value)}
          />
          <span className="bk-sub">
            On this computer. A new folder, or an empty one; saved as the backup storage folder.
          </span>
        </div>
        <div className="bk-field__control">
          <span className="bk-field__label">Password</span>
          {passwordStored && (
            <span className="bk-readonly">
              <LockKeyIcon size={16} /> Set, in .env
            </span>
          )}
          {!passwordStored && mode === "create" && (
            <PasswordFields value={password} onChange={edit(setPassword)} />
          )}
          {!passwordStored && mode === "connect" && (
            <input
              className="input"
              type="password"
              aria-label="Password"
              placeholder="The repository's password"
              value={password.pw}
              onChange={(e) => edit(setPassword)({ ...password, pw: e.target.value })}
            />
          )}
        </div>
        {mode === "connect" && (
          <p className="bk-note">
            <InfoIcon size={16} />
            <span>
              Nothing is saved until the password opens the copy. Then it is saved in .env.
            </span>
          </p>
        )}
        {working && (
          <p className="bk-status__running" role="status">
            <CircleNotchIcon size={14} className="adm-spin" /> {text.working}
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
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void submit()}
            disabled={!ready || working}
          >
            {text.submit}
          </button>
        </div>
      </div>
    </div>
  );
}
