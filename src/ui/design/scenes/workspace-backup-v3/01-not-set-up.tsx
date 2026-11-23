import { BackupPrototype } from "./_prototype";

export const meta = {
  title: "1 · Backup — not set up · v3",
  viewport: "laptop",
  description: "Prototype start before any backup exists: Set up backups opens the form.",
};

export default function Frame() {
  return <BackupPrototype start={{ stage: "off" }} />;
}