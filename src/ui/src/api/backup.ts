import { api } from "./client";
import { type Refusal, refusalOf } from "./refusal";
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

export type BackupConnected = components["schemas"]["BackupConnected"];

/** Set-up's, create's, connect's and restore's answer: started, or a
 * {@link Refusal}. Set-up's names the destination it connected, when one
 * already held a backup. */
export type SetUpOutcome =
  { kind: "started"; status: BackupStatus; connected?: BackupConnected | null } | Refusal;

function message(error: unknown, fallback: string): string {
  const body = error as { detail?: unknown; message?: unknown } | undefined;
  if (typeof body?.detail === "string") return body.detail;
  if (typeof body?.message === "string") return body.message;
  return fallback;
}

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

export async function runBackup(): Promise<BackupStatus> {
  const { data, error } = await api.POST("/api/backup/run");
  if (data) return data;
  throw new Error(message(error, "Could not start a backup"));
}

function outcome(
  { data, error }: { data?: BackupStatus; error?: unknown },
  fallback: string,
): SetUpOutcome {
  if (data) return { kind: "started", status: data };
  const refusal = refusalOf(error);
  if (refusal) return refusal;
  throw new Error(message(error, fallback));
}

export async function setUpBackup(answers: BackupSetUp): Promise<SetUpOutcome> {
  const answer = await api.POST("/api/backup/setup", { body: answers });
  const result = outcome(answer, "Could not set up backups");
  if (result.kind !== "started") return result;
  return { ...result, connected: answer.data?.connected ?? null };
}

export type NewRepository = components["schemas"]["BackupNewRepositoryRequest"];
export type ConnectRepository = components["schemas"]["BackupConnectRequest"];

export async function createRepository(body: NewRepository): Promise<SetUpOutcome> {
  return outcome(
    await api.POST("/api/backup/repository", { body }),
    "Could not create the repository",
  );
}

export async function connectRepository(body: ConnectRepository): Promise<SetUpOutcome> {
  return outcome(
    await api.POST("/api/backup/connect", { body }),
    "Could not connect the repository",
  );
}

export async function repairDestination(destination: string): Promise<RepairResult> {
  const { data, error } = await api.POST("/api/backup/repair", { body: { destination } });
  if (data) return data;
  throw new Error(message(error, "Could not repair the copy"));
}

export type RestoreStatus = components["schemas"]["RestoreStatus"];
export type BackupSnapshot = components["schemas"]["BackupSnapshot"];
export type BackupSnapshots = components["schemas"]["BackupSnapshotsResponse"];

export async function getBackupSnapshots(): Promise<BackupSnapshots> {
  const { data, error } = await api.GET("/api/backup/snapshots");
  if (data) return data;
  throw new Error(message(error, "Could not read the backups"));
}

export async function startRestore(snapshot: string, target: string): Promise<SetUpOutcome> {
  const { data, error } = await api.POST("/api/backup/restore", { body: { snapshot, target } });
  if (data) return { kind: "started", status: data };
  // A refused target is the domain's 409, answered as `detail`.
  const refused = message(error, "Could not start the restore");
  return refusalOf(error) ?? { kind: "refused", message: refused, fieldErrors: {} };
}

export async function stopRestore(): Promise<BackupStatus> {
  const { data, error } = await api.POST("/api/backup/restore/stop");
  if (data) return data;
  throw new Error(message(error, "Could not stop the restore"));
}
