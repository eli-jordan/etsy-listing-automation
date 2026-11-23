import { BackupPrototype } from "./_prototype";

export const meta = {
  title: "9 · Restoring",
  viewport: "laptop",
  description: "A long restore: live progress from restic, time left, and Keep working to close the dialog while it runs.",
};

export default function Frame() {
  return <BackupPrototype start={{ stage: "on", dialog: "restoring" }} />;
}
