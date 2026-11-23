import { BackupPrototype } from "./_prototype";

export const meta = {
  title: "3 · Backup — healthy",
  viewport: "laptop",
  description: "Running backups: summary, Back up now, history with Restore on each saved backup, destinations and Edit settings.",
};

export default function Frame() {
  return <BackupPrototype start={{ stage: "on" }} />;
}