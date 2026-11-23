import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { destinationsBehind, failingRuns } from "./_fixtures";
import { BackupPage, History, StatusPanel, WhereStored } from "./_parts";

export const meta = {
  title: "4 · Backup — failing · v1",
  viewport: "laptop",
  description: "Warning states: iCloud copy 2 days behind, a failed weekly check and a wrong password in history, while a backup waits for a deploy.",
};

export default function Frame() {
  return (
    <BackupPage>
      <div className="adm-warn bk-banner" role="alert">
        <WarningIcon size={18} />
        <span>
          <strong>iCloud Drive hasn't had a backup for 2 days.</strong> The folder{" "}
          <span className="s-mono">C:\Users\Admin\iCloudDrive\naturally-inked-studio-backups</span> wasn't found.
          Check that iCloud for Windows is running and signed in. Backups on this computer are still running.
        </span>
      </div>
      <StatusPanel
        tone="warn"
        headline="Backed up here 2 hours ago, not copied to iCloud Drive"
        detail="The weekly check yesterday found a damaged file. Your backups are still readable, but run the check again."
        running="Backup due. Waiting for the deploy of now-or-never to finish…"
        restoreGoto="workspace-backup-v1/05-restore"
      />
      <History list={failingRuns} restoreGoto="workspace-backup-v1/05-restore" />
      <WhereStored list={destinationsBehind} />
    </BackupPage>
  );
}
