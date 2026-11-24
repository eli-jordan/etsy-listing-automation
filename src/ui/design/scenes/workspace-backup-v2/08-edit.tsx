import { BackupPrototype } from "./_prototype";

export const meta = {
  title: "8 · Backup — edit settings · v2",
  viewport: "laptop",
  description: "Editing a running setup: interval, destinations and retention; the folder and password are fixed here.",
};

export default function Frame() {
  return <BackupPrototype start={{ stage: "edit" }} />;
}