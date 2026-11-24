import { BackupPrototype } from "./_prototype";

export const meta = {
  title: "10 · Restoring in the background",
  viewport: "laptop",
  description: "The dialog closed mid-restore: progress stays on the Backup page, and Show reopens it.",
};

export default function Frame() {
  return <BackupPrototype start={{ stage: "on", restoringInBackground: true }} />;
}
