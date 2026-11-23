// Mocked backup state, shaped like the props the Backup section will take.

export type RunResult = "ok" | "partial" | "failed";

export interface BackupRun {
  id: string;
  /** Local time the run started, already formatted for the row. */
  when: string;
  ago: string;
  result: RunResult;
  /** One line under the result: what was done, or what went wrong. */
  detail: string;
  added: string;
  duration: string;
  /** The restic snapshot this run made; null when the backup step itself failed. */
  snapshot: string | null;
  /** The retention bucket a kept snapshot belongs to. */
  kept?: "recent" | "weekly" | "monthly";
}

export interface Destination {
  id: string;
  name: string;
  path: string;
  checked: string;
}

/** The `backup:` block of settings.yaml, as the form edits it. */
export interface BackupSettings {
  repository: string;
  destinations: Destination[];
  intervalHours: number;
  keepDays: number;
  keepWeeks: number;
  keepMonths: number;
}

export const repository = "C:\\Users\\Admin\\naturally-inked-studio-backups";
export const icloud = "C:\\Users\\Admin\\iCloudDrive\\naturally-inked-studio-backups";

export const defaultSettings: BackupSettings = {
  repository,
  destinations: [{ id: "icloud", name: "iCloud Drive", path: icloud, checked: "sample checked 1 Nov" }],
  intervalHours: 12,
  keepDays: 7,
  keepWeeks: 4,
  keepMonths: 3,
};

export const intervalChoices = [4, 6, 12, 24, 48];

export const runs: BackupRun[] = [
  { id: "r1", when: "Mon 23 Nov, 09:12", ago: "2 hours ago", result: "ok", detail: "Copied to iCloud Drive", added: "41 MB", duration: "48 s", snapshot: "a3f9c2e1", kept: "recent" },
  { id: "r2", when: "Sun 22 Nov, 21:05", ago: "14 hours ago", result: "ok", detail: "Copied to iCloud Drive", added: "312 MB", duration: "1 min 52 s", snapshot: "7be04d19", kept: "recent" },
  { id: "r3", when: "Sun 22 Nov, 09:01", ago: "yesterday", result: "ok", detail: "Copied to iCloud Drive · weekly clean-up and check passed", added: "2 MB", duration: "2 min 40 s", snapshot: "c81a77f0", kept: "recent" },
  { id: "r4", when: "Sat 21 Nov, 20:47", ago: "2 days ago", result: "partial", detail: "Backed up here, but iCloud Drive was unavailable. Caught up at the next run.", added: "88 MB", duration: "39 s", snapshot: "19d3be52", kept: "recent" },
  { id: "r5", when: "Sat 21 Nov, 08:44", ago: "2 days ago", result: "ok", detail: "Copied to iCloud Drive", added: "6 MB", duration: "31 s", snapshot: "e4402a6b", kept: "recent" },
  { id: "r6", when: "Sun 15 Nov, 18:30", ago: "8 days ago", result: "ok", detail: "Latest backup of week 46", added: "—", duration: "—", snapshot: "52c0f1aa", kept: "weekly" },
  { id: "r7", when: "Sat 31 Oct, 19:02", ago: "23 days ago", result: "ok", detail: "Latest backup of October", added: "—", duration: "—", snapshot: "0fa98d3c", kept: "monthly" },
];

export const failingRuns: BackupRun[] = [
  { id: "f1", when: "Mon 23 Nov, 09:12", ago: "2 hours ago", result: "partial", detail: "Backed up here. iCloud Drive folder not found, so it wasn't copied.", added: "41 MB", duration: "44 s", snapshot: "a3f9c2e1", kept: "recent" },
  { id: "f2", when: "Sun 22 Nov, 21:05", ago: "14 hours ago", result: "partial", detail: "Backed up here. iCloud Drive folder not found, so it wasn't copied.", added: "312 MB", duration: "1 min 50 s", snapshot: "7be04d19", kept: "recent" },
  { id: "f3", when: "Sun 22 Nov, 09:01", ago: "yesterday", result: "failed", detail: "Weekly check found 1 damaged pack file. Nothing was deleted. Run the check again, or repair from the iCloud copy.", added: "2 MB", duration: "3 min 05 s", snapshot: "c81a77f0", kept: "recent" },
  { id: "f4", when: "Sat 21 Nov, 20:47", ago: "2 days ago", result: "ok", detail: "Copied to iCloud Drive", added: "88 MB", duration: "39 s", snapshot: "19d3be52", kept: "recent" },
  { id: "f5", when: "Sat 21 Nov, 08:44", ago: "2 days ago", result: "failed", detail: "Wrong repository password. ETSY_LISTINGS_BACKUP_PASSWORD in .env doesn't open this repository.", added: "—", duration: "2 s", snapshot: null },
];

export const restoreTarget = (run: BackupRun) =>
  `C:\\Users\\Admin\\naturally-inked-studio-restore-${run.snapshot ?? "latest"}`;

/** What one whole-workspace snapshot holds, for the restore dialogs. */
export const snapshotSize = { gb: 20.1, files: 5142 };

/** What the copy found in iCloud Drive in the "changed files" frame. */
export interface ChangedFile {
  path: string;
  kind: "changed" | "unexpected";
  detail: string;
}

export const changedFiles: ChangedFile[] = [
  { path: "data/7c/7c41e0d2…b19a2f", kind: "changed", detail: "16.8 MB when copied, 16.1 MB now" },
  { path: "index/a3f9c2e1…77d0c4 2", kind: "unexpected", detail: "Not a name restic writes. Probably an iCloud conflict copy." },
];

export const changedRuns: BackupRun[] = runs.map((r) =>
  r.id === "r1"
    ? { ...r, result: "partial", detail: "Backed up here. Copying to iCloud Drive stopped: a file there changed after it was copied." }
    : r,
);
