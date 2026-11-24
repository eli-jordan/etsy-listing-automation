import { BackupPrototype } from "./_prototype";

export const meta = {
  title: "8 · Backup settings · v3",
  viewport: "laptop",
  description: "The Settings subsection under Backup: interval, destinations and retention. Folder and password are fixed once set.",
};

export default function Frame() {
  return <BackupPrototype start={{ stage: "edit" }} />;
}