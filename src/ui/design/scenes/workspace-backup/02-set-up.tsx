import { BackupPrototype } from "./_prototype";

export const meta = {
  title: "2 · Backup — set up",
  viewport: "laptop",
  description: "Setup form: folder, interval (4 h to 2 days), password with a saved-elsewhere check, destinations and retention. Create runs the first backup.",
};

export default function Frame() {
  return <BackupPrototype start={{ stage: "setup" }} />;
}