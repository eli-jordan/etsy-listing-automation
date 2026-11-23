import { BackupPrototype } from "./_prototype";

export const meta = {
  title: "11 · Warning on every page",
  viewport: "laptop",
  description: "Backups failing while the seller works elsewhere: a banner on every page and a dot on Admin, until a backup succeeds.",
};

export default function Frame() {
  return <BackupPrototype start={{ stage: "on", failing: true, page: "dashboard" }} />;
}
