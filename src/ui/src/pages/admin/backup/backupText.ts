import type {
  BackupSnapshot,
  BackupStatus,
  BackupWarning,
  HistoryEntry,
  IntervalHours,
  RepairResult,
  RestoreStatus,
  RetentionSettings,
  RunningBackup,
} from "../../../api/backup";
import { timeAgo } from "../../editor/timeAgo";

export const INTERVALS = [4, 6, 12, 24, 48] as const;

/** What Set up and Setup edit: settings.yaml's `backup:` block. */
export interface BackupAnswers {
  repository: string;
  destinations: string[];
  interval_hours: IntervalHours;
  retention: RetentionSettings;
}

export const NEW_BACKUP: BackupAnswers = {
  repository: "",
  destinations: [],
  interval_hours: 12,
  retention: { keep_within_days: 7, weekly: 4, monthly: 3 },
};

/** "iCloud Drive" for an iCloud folder, else the folder's own name. */
export function destinationName(path: string): string {
  if (/icloud/i.test(path)) return "iCloud Drive";
  return lastPart(path) || "Folder";
}

export function lastPart(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

export function everyLabel(hours: number): string {
  if (hours === 24) return "Every day";
  if (hours % 24 === 0) return `Every ${hours / 24} days`;
  return `Every ${hours} hours`;
}

export function intervalChoice(hours: number): string {
  if (hours === 24) return "1 day";
  return hours % 24 === 0 ? `${hours / 24} days` : `${hours} hours`;
}

export function intervalHint(hours: number): string {
  if (hours < 12)
    return "More often means less to lose, and a short pause for your jobs more often.";
  if (hours > 12)
    return `Up to ${intervalChoice(hours)} of work could be lost if this computer fails.`;
  return "Recommended: at most half a day of work to lose.";
}

export function ago(iso: string, now: number): string {
  return timeAgo(Date.parse(iso), now);
}

/** "Mon 23 Nov, 09:12", in the seller's time zone. */
export function when(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function bytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = n;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  // "16.8 MB", "41 MB", "312 MB": a tenth only while it still says something.
  const shown = unit === 0 || value >= 100 ? Math.round(value) : Number(value.toFixed(1));
  return `${shown} ${units[unit]}`;
}

export function duration(from: string, to: string): string {
  const seconds = Math.max(0, Math.round((Date.parse(to) - Date.parse(from)) / 1000));
  if (seconds < 60) return `${seconds} s`;
  return `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
}

const STEPS: Record<string, string> = {
  starting: "Starting…",
  forgetting: "Removing expired backups…",
  pruning: "Cleaning up the backup storage folder…",
  checking: "Checking the backup storage folder…",
};

/** What the operation in progress is doing, for the line under the detail. */
export function runningLine(running: RunningBackup): string {
  const name = running.destination ? destinationName(running.destination) : "the destination";
  const counted = filesCounted(running);
  if (running.operation === "repair") return `Repairing the ${name} copy…`;
  if (running.step === "waiting" && running.waiting_for)
    return `Waiting for ${running.waiting_for} to finish…`;
  if (running.step === "backing_up")
    return counted ? `Backing up…${counted} checked` : "Backing up…";
  if (running.step === "copying") return `Copying new files to ${name}…${counted}`;
  if (running.step === "checking_copy") return `Checking the copy in ${name}…`;
  return STEPS[running.step] ?? "Backing up…";
}

function filesCounted({ files_done: done, files_total: total }: RunningBackup): string {
  if (done == null || total == null) return "";
  return ` ${done.toLocaleString("en-GB")} of ${total.toLocaleString("en-GB")} files`;
}

/** The status panel's headline and detail. */
export function summary(
  status: BackupStatus,
  now: number,
): { tone: "ok" | "warn"; headline: string; detail: string } {
  const last = status.last_success ? `Backed up ${ago(status.last_success, now)}` : null;
  const warnings = status.warnings.filter((w) => w.banner);
  const kept = `${status.repository?.snapshots ?? 0} backups kept`;
  const every = everyLabel(status.interval_hours ?? 12).toLowerCase();
  if (status.running?.operation === "backup" && !status.last_success)
    return {
      tone: "ok",
      headline: "Making the first backup",
      detail: "The whole workspace. Deploys, Prepare and AI runs you start wait until it's done.",
    };
  if (status.running)
    return {
      tone: "ok",
      headline: last ?? "Backing up",
      detail: "Jobs you start now wait until this backup finishes, usually under a minute.",
    };
  const changed = warnings.find((w) => w.kind === "changed");
  if (changed) {
    const name = destinationName(changed.destination ?? "");
    return {
      tone: "warn",
      headline: `${last ?? "Not backed up"}, ${name} copy stopped`,
      detail: `Something changed files in the ${name} copy. Nothing there was overwritten. The backups on this computer are fine.`,
    };
  }
  const behind = warnings.find((w) => w.kind === "behind");
  const headline = behind
    ? `${last ?? "Not backed up"}, not copied to ${destinationName(behind.destination ?? "")}`
    : (last ?? "No backups yet");
  return {
    tone: warnings.length ? "warn" : "ok",
    headline,
    detail: `${nextLine(status.next_due, now)} · ${every} · ${kept}`,
  };
}

function nextLine(due: string | null | undefined, now: number): string {
  if (!due) return "No backup scheduled";
  const hours = Math.round((Date.parse(due) - now) / 3_600_000);
  if (hours <= 0) return "Next backup due now";
  return `Next backup in about ${hours} hour${hours === 1 ? "" : "s"}`;
}

/** The warnings that a Try again answers: all but changed files and a
 * missing repository, which have their own actions. */
export function retryable(warning: BackupWarning): boolean {
  return warning.kind === "stale" || warning.kind === "failed" || warning.kind === "behind";
}

export type RowResult = "ok" | "partial" | "failed" | "stopped";

/** A history row's result and the one line under it. */
export function rowResult(entry: HistoryEntry): { result: RowResult; detail: string } {
  const { run } = entry;
  if (run.outcome === "failed")
    return {
      result: "failed",
      detail: run.message ?? `Failed while ${run.failed_step ?? "backing up"}.`,
    };
  if (run.outcome === "stopped")
    return { result: "stopped", detail: run.message ?? "Stopped when the app closed." };
  const missed = run.copies.filter((copy) => copy.outcome !== "copied");
  if (missed.length)
    return {
      result: "partial",
      detail: `Backed up here. ${missed
        .map((copy) => `${destinationName(copy.destination)}: ${copy.message ?? copy.outcome}`)
        .join(" ")}`,
    };
  return {
    result: "ok",
    detail: run.copies.length
      ? `Copied to ${run.copies.map((copy) => destinationName(copy.destination)).join(", ")}`
      : "Kept on this computer",
  };
}

/** The note a finished repair leaves in the status panel. */
export function repairNote(path: string, result: RepairResult): string {
  const moved = result.moved.length;
  const files = moved === 1 ? "1 file was" : `${moved} files were`;
  const aside = result.set_aside
    ? ` ${files} set aside in ${lastPart(result.set_aside)}, next to it.`
    : "";
  const after =
    result.outcome === "copied" ? "" : ` The copy again: ${result.message ?? result.outcome}.`;
  return `Repaired the ${destinationName(path)} copy.${aside}${after}`;
}

/** A restore's progress, worded as the prototype's `restoreFigures`. */
export function restoreFigures(restore: RestoreStatus) {
  const { bytes_total: total, files_total: files, seconds_left: left } = restore;
  const count = (n: number) => n.toLocaleString("en-GB");
  return {
    pctText: `${Math.round(restore.percent * 100)}%`,
    bytes: total == null ? "" : bytesOf(restore.bytes_done ?? 0, total),
    files: files == null ? "" : `${count(restore.files_done ?? 0)} of ${count(files)} files`,
    left:
      left == null
        ? "working out the time left"
        : `about ${Math.max(1, Math.ceil(left / 60))} min left`,
  };
}

/** "7.6 of 20.1 GB": the unit once when both share it, as the prototype words it. */
function bytesOf(done: number, total: number): string {
  const [part, whole] = [bytes(done), bytes(total)];
  const unit = whole.slice(whole.indexOf(" "));
  return part.endsWith(unit) ? `${part.slice(0, -unit.length)} of ${whole}` : `${part} of ${whole}`;
}

/** The parts that are known, joined as the prototype joins figures. */
export const joined = (...parts: string[]) => parts.filter(Boolean).join(" · ");

/** Without trailing separators; a loop, as a regex here would backtrack. */
function trimmed(path: string): string {
  let end = path.length;
  while (end > 0 && "/\\".includes(path.charAt(end - 1))) end -= 1;
  return path.slice(0, end);
}

/** The restore dialog's default: the workspace's sibling, named after the snapshot. */
export function restoreTarget(workspace: string, snapshot: BackupSnapshot): string {
  return `${trimmed(workspace)}-restore-${snapshot.short_id}`;
}

/** Whether two paths name one folder, as Windows compares them. */
export function samePath(a: string, b: string): boolean {
  const normal = (path: string) => trimmed(path.trim()).replaceAll("\\", "/").toLowerCase();
  return normal(a) === normal(b);
}

/** The status panel's note once a restore has ended. */
export function restoreNote(restore: RestoreStatus): string {
  const left =
    "The folder holds the files restored so far; delete it before restoring there again.";
  const at = `${Math.round(restore.percent * 100)}%`;
  if (restore.outcome === "succeeded")
    return `Restored the backup from ${when(restore.snapshot_time)}.`;
  if (restore.outcome === "stopped") return `Restore stopped at ${at}. ${left}`;
  return `The restore failed at ${at}: ${restore.message ?? "no reason was given"} ${left}`;
}
