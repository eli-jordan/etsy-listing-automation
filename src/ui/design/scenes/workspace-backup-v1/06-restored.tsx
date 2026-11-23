import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { CopyIcon } from "@phosphor-icons/react/dist/csr/Copy";
import { destinations, restoreTarget, runs } from "./_fixtures";
import { BackupPage, History, StatusPanel, WhereStored } from "./_parts";

export const meta = {
  title: "6 · Restore finished · v1",
  viewport: "laptop",
  description: "Restore done: where the files are and the two ways to use them, pointing the app at the folder or copying files back.",
};

export default function Frame() {
  return (
    <>
      <BackupPage>
        <StatusPanel
          tone="ok"
          headline="Backed up 2 hours ago"
          detail="Next backup in about 10 hours · 7 backups kept, 23.4 GB stored"
        />
        <History list={runs} />
        <WhereStored list={destinations} />
      </BackupPage>
      <div className="bk-scrim">
        <div className="bk-dialog" role="dialog" aria-modal="true" aria-labelledby="bk-done-title">
          <span className="bk-done-icon" aria-hidden="true">
            <CheckIcon size={24} weight="bold" />
          </span>
          <div>
            <h2 className="bk-dialog__title" id="bk-done-title">
              Restored 5,142 files
            </h2>
            <p className="bk-dialog__lede">The workspace from Sun 22 Nov, 21:05 is in this folder:</p>
          </div>
          <div className="bk-inline">
            <input className="input s-mono" aria-label="Restored folder" readOnly value={restoreTarget} />
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
            <button type="button" className="btn btn-primary" data-goto="workspace-backup-v1/03-overview">
              Done
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
