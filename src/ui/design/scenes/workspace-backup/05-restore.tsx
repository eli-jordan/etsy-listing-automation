import { BackupPrototype } from "./_prototype";

export const meta = {
  title: "5 · Restore a backup",
  viewport: "laptop",
  description: "Restore dialog: pick a backup and a new folder; the live workspace is refused. Restore runs, then reports.",
};

export default function Frame() {
  return <BackupPrototype start={{ stage: "on", dialog: "restore" }} />;
}