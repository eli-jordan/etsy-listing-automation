import { BackupPrototype } from "./_prototype";

export const meta = {
  title: "4 · Backup — failing · v3",
  viewport: "laptop",
  description: "Warning states: iCloud copy 2 days behind, failed check and wrong-password runs. Try again clears them.",
};

export default function Frame() {
  return <BackupPrototype start={{ stage: "on", failing: true }} />;
}