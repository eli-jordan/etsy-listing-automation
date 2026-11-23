import { api } from "./client";
import type { components } from "./schema";

export type BackupStatus = components["schemas"]["BackupOverview"];
export type BackupWarning = components["schemas"]["BackupWarning"];
export type DestinationStatus = components["schemas"]["DestinationOverview"];
export type RunningBackup = components["schemas"]["RunningBackup"];
export type HistoryEntry = components["schemas"]["HistoryEntry"];
export type BackupSetUp = components["schemas"]["BackupSetUpRequest"];
export type RepairResult = components["schemas"]["BackupRepairResponse"];
export type IntervalHours = BackupSetUp["interval_hours"];
type Refusal = components["schemas"]["SettingsSaveRefusal"];

/** Set-up's answer: started, or refused with the field it names. */
export type SetUpOutcome =
  | { kind: "started"; status: BackupStatus }
  | { kind: "conflict" | "invalid"; message: string; fieldErrors: Record<string, string> };

function message(error: unknown, fallback: string): string {
  const body = error as { detail?: unknown; message?: unknown } | undefined;
  if (typeof body?.detail === "string") return body.detail;
  if (typeof body?.message === "string") return body.message;
  return fallback;
}

/** The one status source for the Backup page, the banner and both nav icons. */
export async function getBackupStatus(): Promise<BackupStatus> {
  const { data, error } = await api.GET("/api/backup");
  if (data) return data;
  throw new Error(message(error, "Could not read the backup status"));
}

export async function getBackupHistory(): Promise<HistoryEntry[]> {
  const { data, error } = await api.GET("/api/backup/history");
  if (data) return data.runs;
  throw new Error(message(error, "Could not read the backup history"));
}

/** Back up now. A backup operation already running is a 409. */
export async function runBackup(): Promise<BackupStatus> {
  const { data, error } = await api.POST("/api/backup/run");
  if (data) return data;
  throw new Error(message(error, "Could not start a backup"));
}

export async function setUpBackup(answers: BackupSetUp): Promise<SetUpOutcome> {
  const { data, error } = await api.POST("/api/backup/setup", { body: answers });
  if (data) return { kind: "started", status: data };
  const refusal = error as Refusal | undefined;
  if (refusal?.kind === "conflict" || refusal?.kind === "invalid")
    return {
      kind: refusal.kind,
      message: refusal.message,
      fieldErrors: refusal.field_errors ?? {},
    };
  throw new Error(message(error, "Could not set up backups"));
}

/** Set aside a destination's changed files and copy again; answers when done. */
export async function repairDestination(destination: string): Promise<RepairResult> {
  const { data, error } = await api.POST("/api/backup/repair", { body: { destination } });
  if (data) return data;
  throw new Error(message(error, "Could not repair the copy"));
}
