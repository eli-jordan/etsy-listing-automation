import { api } from "./client";
import type { components } from "./schema";

export type BackupStatus = components["schemas"]["BackupOverview"];
export type BackupWarning = components["schemas"]["BackupWarning"];
export type DestinationStatus = components["schemas"]["DestinationOverview"];
export type RunningBackup = components["schemas"]["RunningBackup"];
export type HistoryEntry = components["schemas"]["HistoryEntry"];
export type BackupSetUp = components["schemas"]["BackupSetUpRequest"];
export type RepairResult = components["schemas"]["BackupRepairResponse"];
export type BackupSettings = components["schemas"]["BackupSettings"];
export type RetentionSettings = components["schemas"]["RetentionSettings"];
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

function outcome(data: BackupStatus | undefined, error: unknown, fallback: string): SetUpOutcome {
  if (data) return { kind: "started", status: data };
  const refusal = error as Refusal | undefined;
  if (refusal?.kind === "conflict" || refusal?.kind === "invalid")
    return {
      kind: refusal.kind,
      message: refusal.message,
      fieldErrors: refusal.field_errors ?? {},
    };
  throw new Error(message(error, fallback));
}

export async function setUpBackup(answers: BackupSetUp): Promise<SetUpOutcome> {
  const { data, error } = await api.POST("/api/backup/setup", { body: answers });
  return outcome(data, error, "Could not set up backups");
}

export type NewRepository = components["schemas"]["BackupNewRepositoryRequest"];
export type ConnectRepository = components["schemas"]["BackupConnectRequest"];

/** Create a new repository while the configured one is missing; starts the
 * first backup. Refusals come back as set-up's do. */
export async function createRepository(body: NewRepository): Promise<SetUpOutcome> {
  const { data, error } = await api.POST("/api/backup/repository", { body });
  return outcome(data, error, "Could not create the repository");
}

/** Copy an existing repository to this computer and use it; answers once
 * it is connected. A wrong password is an `invalid` refusal. */
export async function connectRepository(body: ConnectRepository): Promise<SetUpOutcome> {
  const { data, error } = await api.POST("/api/backup/connect", { body });
  return outcome(data, error, "Could not connect the repository");
}

/** Set aside a destination's changed files and copy again; answers when done. */
export async function repairDestination(destination: string): Promise<RepairResult> {
  const { data, error } = await api.POST("/api/backup/repair", { body: { destination } });
  if (data) return data;
  throw new Error(message(error, "Could not repair the copy"));
}

export type RestoreStatus = components["schemas"]["RestoreStatus"];
export type BackupSnapshot = components["schemas"]["BackupSnapshot"];
export type BackupSnapshots = components["schemas"]["BackupSnapshotsResponse"];

/** restic's own snapshots, newest first, with the live workspace's path. */
export async function getBackupSnapshots(): Promise<BackupSnapshots> {
  const { data, error } = await api.GET("/api/backup/snapshots");
  if (data) return data;
  throw new Error(message(error, "Could not read the backups"));
}

/** Start a restore. A refusal (the live workspace, a folder with files, a
 * restore already running) comes back as its message, for under the field. */
export async function startRestore(
  snapshot: string,
  target: string,
): Promise<{ status: BackupStatus } | { refused: string }> {
  const { data, error } = await api.POST("/api/backup/restore", { body: { snapshot, target } });
  if (data) return { status: data };
  return { refused: message(error, "Could not start the restore") };
}

/** Stop the restore; answers once it has stopped. */
export async function stopRestore(): Promise<BackupStatus> {
  const { data, error } = await api.POST("/api/backup/restore/stop");
  if (data) return data;
  throw new Error(message(error, "Could not stop the restore"));
}
