import { BackupPrototype } from "./_prototype";

export const meta = {
  title: "7 · Backup — running · v3",
  viewport: "laptop",
  description: "Back up now in progress: waits for a deploy, checks files, copies to iCloud Drive, then the new row lands in history.",
};

export default function Frame() {
  return <BackupPrototype start={{ stage: "on", running: true }} />;
}