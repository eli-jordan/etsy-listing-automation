import { CloudArrowUpIcon } from "@phosphor-icons/react/dist/csr/CloudArrowUp";
import { EyeIcon } from "@phosphor-icons/react/dist/csr/Eye";
import { FolderOpenIcon } from "@phosphor-icons/react/dist/csr/FolderOpen";
import { PlusIcon } from "@phosphor-icons/react/dist/csr/Plus";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { useState } from "react";
import { icloud, repository } from "./_fixtures";
import { BackupPage, Panel } from "./_parts";

export const meta = {
  title: "2 · Backup — set up · v1",
  viewport: "laptop",
  description: "Setup form: local repository folder, password with a saved-elsewhere confirmation, destinations, and retention. Creating it leads to the overview.",
};

export default function Frame() {
  const [saved, setSaved] = useState(false);
  return (
    <BackupPage>
      <Panel
        id="bk-setup"
        title="Set up backups"
        lede="Saved to the backup block in settings.yaml. The password goes in the workspace's .env file, never in settings.yaml."
      >
        <div className="bk-form">
          <div className="bk-field">
            <span className="bk-field__label">
              Backup folder
              <span className="bk-sub">On this computer, outside any synced folder. Backups and clean-up run here.</span>
            </span>
            <div className="bk-field__control">
              <div className="bk-inline">
                <input className="input s-mono" aria-label="Backup folder" defaultValue={repository} />
                <button type="button" className="btn btn-secondary">
                  <FolderOpenIcon size={16} /> Choose…
                </button>
              </div>
              <span className="bk-sub">Empty folder · 183 GB free on C:</span>
            </div>
          </div>

          <div className="bk-field">
            <span className="bk-field__label">
              Password
              <span className="bk-sub">Encrypts every backup. Saved as ETSY_LISTINGS_BACKUP_PASSWORD in .env.</span>
            </span>
            <div className="bk-field__control">
              <div className="bk-inline bk-pw">
                <input className="input" type="password" aria-label="Password" placeholder="Password" defaultValue="correct-horse-battery" />
                <input className="input" type="password" aria-label="Repeat password" placeholder="Repeat password" defaultValue="correct-horse-battery" />
                <button type="button" className="btn btn-secondary" aria-label="Show password">
                  <EyeIcon size={16} /> Show
                </button>
              </div>
              <label className="bk-check">
                <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} />
                <span>
                  I've saved this password in my password manager. A backup restored to a new computer can't be
                  opened without it, because the copy of .env inside the backup is encrypted too.
                </span>
              </label>
            </div>
          </div>

          <div className="bk-field">
            <span className="bk-field__label">
              Copy to
              <span className="bk-sub">Each backup copies one way to these folders. An unavailable one catches up at the next run.</span>
            </span>
            <div className="bk-field__control">
              <div className="sa-table">
                <div className="sa-row bk-dest">
                  <CloudArrowUpIcon size={18} />
                  <span className="sa-row__label">iCloud Drive</span>
                  <span className="sa-row__value">
                    <span className="s-mono">{icloud}</span>
                  </span>
                  <button type="button" className="btn btn-ghost" aria-label="Remove iCloud Drive">
                    <XIcon size={16} />
                  </button>
                </div>
              </div>
              <div>
                <button type="button" className="btn btn-secondary bk-add">
                  <PlusIcon size={16} /> Add destination
                </button>
              </div>
            </div>
          </div>

          <div className="bk-field">
            <span className="bk-field__label">
              Keep
              <span className="bk-sub">A backup runs 12 hours after the last one that succeeded.</span>
            </span>
            <div className="bk-field__control">
              <div className="bk-keep">
                <label>
                  <input className="input" aria-label="Days to keep every backup" defaultValue="7" /> days of every backup
                </label>
                <label>
                  <input className="input" aria-label="Weeks to keep" defaultValue="4" /> weeks, latest each week
                </label>
                <label>
                  <input className="input" aria-label="Months to keep" defaultValue="3" /> months, latest each month
                </label>
              </div>
            </div>
          </div>

          <div className="bk-foot">
            <span className="bk-foot__note">
              The first backup copies the whole workspace (about 20 GB) and can take 20 minutes or more. Jobs you
              start meanwhile wait until it finishes.
            </span>
            <button type="button" className="btn btn-ghost" data-goto="workspace-backup-v1/01-not-set-up">
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={!saved}
              data-goto={saved ? "workspace-backup-v1/03-overview" : undefined}
            >
              Create and back up now
            </button>
          </div>
        </div>
      </Panel>
    </BackupPage>
  );
}
