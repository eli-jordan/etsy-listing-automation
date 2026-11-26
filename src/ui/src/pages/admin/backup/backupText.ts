import type {
  BackupConnected,
  BackupStatus,
  DestinationStatus,
  HistoryEntry,
  IntervalHours,
  RepairResult,
  RestoreStatus,
  RetentionSettings,
  RunningBackup,
} from "../../../api/backup";
import type { BackupsOn } from "../../../shell/backupAttention";
import { timeAgo } from "../../editor/timeAgo";

/** The message a refused submit shows; null when it went through. */
export type SubmitFailure = string | null;

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

/** What the server calls a destination (`name`), or, for one it does not
 * list, the folder's own name. */
export function nameOf(status: BackupStatus, path: string): string {
  return status.destinations.find((d) => d.path === path)?.name ?? lastPart(path);
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

export function when(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Values from here up drop the tenth. */
const WHOLE_FROM = 100;

export function bytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = n;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  const shown = unit === 0 || value >= WHOLE_FROM ? Math.round(value) : Number(value.toFixed(1));
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

export function runningLine(status: BackupStatus, running: RunningBackup): string {
  const name = running.destination ? nameOf(status, running.destination) : "the destination";
  const counted = filesCounted(running);
  if (running.operation === "repair") return `Repairing the ${name} copy…`;
  if (running.operation === "connect") return connectingLine(status, running.destination);
  if (running.step === "waiting" && running.waiting_for)
    return `Waiting for ${running.waiting_for} to finish…`;
  if (running.step === "backing_up")
    return counted ? `Backing up…${counted} checked` : "Backing up…";
  if (running.step === "copying") return `Copying new files to ${name}…${counted}`;
  if (running.step === "checking_copy") return `Checking the copy in ${name}…`;
  return STEPS[running.step] ?? "Backing up…";
}

export function connectingLine(status: BackupStatus, source?: string | null): string {
  if (!source) return "Copying the existing backup to this computer…";
  return `Connecting to the backup in ${nameOf(status, source)}… Copying it to this computer can take a while.`;
}

export function connectedNote(status: BackupStatus, connected: BackupConnected): string {
  const count = `${connected.snapshots} ${connected.snapshots === 1 ? "snapshot" : "snapshots"}`;
  const note = `Connected to the backup in ${nameOf(status, connected.destination)}: ${count}.`;
  return connected.notice ? `${note} ${connected.notice}` : note;
}

function filesCounted({ files_done: done, files_total: total }: RunningBackup): string {
  if (done == null || total == null) return "";
  return ` ${done.toLocaleString("en-GB")} of ${total.toLocaleString("en-GB")} files`;
}

export function summary(
  { status, warnings }: BackupsOn,
  now: number,
): { tone: "ok" | "warn"; headline: string; detail: string } {
  const last = status.last_success ? `Backed up ${ago(status.last_success, now)}` : null;
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
    const name = nameOf(status, changed.destination ?? "");
    return {
      tone: "warn",
      headline: `${last ?? "Not backed up"}, ${name} copy stopped`,
      detail: `Something changed files in the ${name} copy. Nothing there was overwritten. The backups on this computer are fine.`,
    };
  }
  const behind = warnings.find((w) => w.kind === "behind");
  const headline = behind
    ? `${last ?? "Not backed up"}, not copied to ${nameOf(status, behind.destination ?? "")}`
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

export type RowResult = "ok" | "partial" | "failed" | "stopped";

export function rowResult(entry: HistoryEntry): { result: RowResult; detail: string } {
  const { result, detail } = runResult(entry);
  return { result, detail: entry.run.notice ? `${detail}. ${entry.run.notice}` : detail };
}

function runResult(entry: HistoryEntry): { result: RowResult; detail: string } {
  const { run } = entry;
  const name = (path: string) => entry.names[path] ?? lastPart(path);
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
        .map((copy) => `${name(copy.destination)}: ${copy.message ?? copy.outcome}`)
        .join(" ")}`,
    };
  return {
    result: "ok",
    detail: run.copies.length
      ? `Copied to ${run.copies.map((copy) => name(copy.destination)).join(", ")}`
      : "Kept on this computer",
  };
}

export function repairNote(destination: DestinationStatus, result: RepairResult): string {
  const moved = result.moved.length;
  const files = moved === 1 ? "1 file was" : `${moved} files were`;
  const aside = result.set_aside
    ? ` ${files} set aside in ${lastPart(result.set_aside)}, next to it.`
    : "";
  const after =
    result.outcome === "copied" ? "" : ` The copy again: ${result.message ?? result.outcome}.`;
  return `Repaired the ${destination.name} copy.${aside}${after}`;
}

export function restoreFigures(restore: RestoreStatus) {
  const { bytes_total: total, files_total: files, seconds_left: left } = restore;
  const count = (n: number) => n.toLocaleString("en-GB");
  return {
    pctText: `${Math.round(restore.fraction * 100)}%`,
    bytes: total == null ? "" : bytesProgress(restore.bytes_done ?? 0, total),
    files: files == null ? "" : `${count(restore.files_done ?? 0)} of ${count(files)} files`,
    left:
      left == null
        ? "working out the time left"
        : `about ${Math.max(1, Math.ceil(left / 60))} min left`,
  };
}

export function bytesProgress(done: number, total: number): string {
  const [part, whole] = [bytes(done), bytes(total)];
  const unit = whole.slice(whole.indexOf(" "));
  return part.endsWith(unit) ? `${part.slice(0, -unit.length)} of ${whole}` : `${part} of ${whole}`;
}

export const joined = (...parts: string[]) => parts.filter(Boolean).join(" · ");

function withoutTrailingSeparators(path: string): string {
  let end = path.length;
  while (end > 0 && "/\\".includes(path.charAt(end - 1))) end -= 1;
  return path.slice(0, end);
}

export function samePath(a: string, b: string): boolean {
  const normal = (path: string) =>
    withoutTrailingSeparators(path.trim()).replaceAll("\\", "/").toLowerCase();
  return normal(a) === normal(b);
}

export function restoreNote(restore: RestoreStatus): string {
  const left =
    "The folder holds the files restored so far; delete it before restoring there again.";
  const at = `${Math.round(restore.fraction * 100)}%`;
  if (restore.outcome === "succeeded")
    return `Restored the backup from ${when(restore.snapshot_time)}.`;
  if (restore.outcome === "stopped") return `Restore stopped at ${at}. ${left}`;
  return `The restore failed at ${at}: ${restore.message ?? "no reason was given"} ${left}`;
}

export interface Password {
  typed: string;
  repeated: string;
  savedInManager: boolean;
}

export function passwordProblem({ typed, repeated }: Password, minLength: number): string | null {
  if (typed.length < minLength) return `Use at least ${minLength} characters.`;
  if (typed !== repeated) return "The two passwords don't match.";
  return null;
}
