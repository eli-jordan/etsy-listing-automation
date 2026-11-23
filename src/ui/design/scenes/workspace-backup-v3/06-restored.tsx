import { BackupPrototype } from "./_prototype";

export const meta = {
  title: "6 · Restore finished · v3",
  viewport: "laptop",
  description: "Restore done: where the files are and the two ways to use them.",
};

export default function Frame() {
  return <BackupPrototype start={{ stage: "on", dialog: "restored" }} />;
}