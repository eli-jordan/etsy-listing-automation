import { destinations, runs } from "./_fixtures";
import { BackupPage, History, StatusPanel, WhereStored } from "./_parts";

export const meta = {
  title: "3 · Backup — healthy · v1",
  viewport: "laptop",
  description: "Settings > Backup once running: health summary, where backups go, and the run history with Restore on every saved backup.",
};

export default function Frame() {
  return (
    <BackupPage>
      <StatusPanel
        tone="ok"
        headline="Backed up 2 hours ago"
        detail="Next backup in about 10 hours · 7 backups kept, 23.4 GB stored"
        restoreGoto="workspace-backup-v1/05-restore"
      />
      <History list={runs} restoreGoto="workspace-backup-v1/05-restore" />
      <WhereStored list={destinations} />
    </BackupPage>
  );
}
