import { ClockCounterClockwiseIcon } from "@phosphor-icons/react/dist/csr/ClockCounterClockwise";
import { CloudArrowUpIcon } from "@phosphor-icons/react/dist/csr/CloudArrowUp";
import { LockKeyIcon } from "@phosphor-icons/react/dist/csr/LockKey";
import { BackupPage, Panel } from "./_parts";

export const meta = {
  title: "1 · Backup — not set up · v1",
  viewport: "laptop",
  description: "Settings > Backup before any repository exists: what backups do, and the one action that starts setup.",
};

export default function Frame() {
  return (
    <BackupPage>
      <Panel
        id="bk-off"
        title="Backups are off"
        lede="This workspace isn't backed up yet. Set up a backup and the app saves a copy of everything in it every 12 hours, while it's open."
      >
        <ul className="bk-steps bk-intro">
          <li>
            <ClockCounterClockwiseIcon size={16} /> <strong>Every 12 hours.</strong> Each backup only stores what
            changed, so it usually takes under a minute. Deploys, Prepare and AI runs wait while it runs.
          </li>
          <li>
            <LockKeyIcon size={16} /> <strong>Encrypted with your password.</strong> Without it no backup can be
            opened, so keep a copy in your password manager.
          </li>
          <li>
            <CloudArrowUpIcon size={16} /> <strong>Stored here, copied to the cloud.</strong> Backups go to a
            folder on this computer first, then copy to destinations such as iCloud Drive or a NAS.
          </li>
        </ul>
        <div className="bk-foot">
          <span className="bk-foot__note">
            Already have backups from another computer? Set up, then connect the existing repository instead
            of creating one.
          </span>
          <button type="button" className="btn btn-primary" data-goto="workspace-backup-v1/02-set-up">
            Set up backups
          </button>
        </div>
      </Panel>
    </BackupPage>
  );
}
