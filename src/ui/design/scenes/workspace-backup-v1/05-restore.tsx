import { FolderOpenIcon } from "@phosphor-icons/react/dist/csr/FolderOpen";
import { InfoIcon } from "@phosphor-icons/react/dist/csr/Info";
import { destinations, restoreTarget, runs } from "./_fixtures";
import { BackupPage, History, StatusPanel, WhereStored } from "./_parts";

export const meta = {
  title: "5 · Restore a backup · v1",
  viewport: "laptop",
  description: "Restore dialog over the overview: the chosen backup's facts and a new target folder. Never restores over the live workspace.",
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
        <div className="bk-dialog" role="dialog" aria-modal="true" aria-labelledby="bk-restore-title">
          <div>
            <h2 className="bk-dialog__title" id="bk-restore-title">
              Restore the backup from Sun 22 Nov, 21:05
            </h2>
            <p className="bk-dialog__lede">
              The whole workspace as it was then, written into a new folder. Your current workspace isn't changed.
            </p>
          </div>
          <dl className="bk-facts">
            <dt>Backup</dt>
            <dd>
              <label className="bk-pick">
                <select aria-label="Backup to restore" defaultValue="7be04d19">
                  {runs
                    .filter((r) => r.snapshot)
                    .map((r) => (
                      <option key={r.id} value={r.snapshot ?? ""}>
                        {r.when} ({r.ago})
                      </option>
                    ))}
                </select>
              </label>
            </dd>
            <dt>Size</dt>
            <dd>20.1 GB · 5,142 files</dd>
            <dt>Listings</dt>
            <dd>34 listings, 19 batches</dd>
          </dl>
          <div className="bk-field__control">
            <span className="bk-field__label">Restore into</span>
            <div className="bk-inline">
              <input className="input s-mono" aria-label="Restore into" defaultValue={restoreTarget} />
              <button type="button" className="btn btn-secondary">
                <FolderOpenIcon size={16} /> Choose…
              </button>
            </div>
            <span className="bk-sub">A new folder. A folder that already has files in it isn't accepted.</span>
          </div>
          <p className="bk-note">
            <InfoIcon size={16} />
            <span>
              About 20 GB is read from the backup on this computer. Nothing is downloaded from iCloud Drive.
            </span>
          </p>
          <div className="bk-dialog__foot">
            <button type="button" className="btn btn-ghost" data-goto="workspace-backup-v1/03-overview">
              Cancel
            </button>
            <button type="button" className="btn btn-primary" data-goto="workspace-backup-v1/06-restored">
              Restore to this folder
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
