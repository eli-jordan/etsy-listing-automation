import { BackupPrototype } from "./_prototype";

export const meta = {
  title: "12 · Changed files in a destination",
  viewport: "laptop",
  description: "A file in iCloud Drive changed after it was copied, and an iCloud conflict copy appeared: copying stops, and Repair sets them aside.",
};

export default function Frame() {
  return <BackupPrototype start={{ stage: "on", changed: true }} />;
}
