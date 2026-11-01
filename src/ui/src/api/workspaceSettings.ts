import { api } from "./client";
import type { components } from "./schema";

export type WorkspaceSettings = components["schemas"]["WorkspaceSettingsResponse"];
export type SettingsChanges = components["schemas"]["WorkspaceSettingsChanges"];
export type ProviderPreference = components["schemas"]["AiProviderSettings"];
export type ModelCatalogs = components["schemas"]["ModelCatalogs"];
type Refusal = components["schemas"]["SettingsSaveRefusal"];
export type SettingsOutcome =
  | { kind: "saved"; settings: WorkspaceSettings }
  | { kind: "conflict"; message: string }
  | { kind: "invalid"; message: string; fieldErrors: Record<string, string> };

export async function getSettings(): Promise<WorkspaceSettings> {
  const { data, error } = await api.GET("/api/admin/settings");
  if (data) return data;
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  throw new Error(typeof detail === "string" ? detail : "Could not read settings.yaml");
}

export async function getModelCatalogs(refresh = false): Promise<ModelCatalogs> {
  const { data } = await api.GET("/api/admin/settings/models", {
    params: { query: { refresh } },
  });
  if (data) return data;
  throw new Error("Could not read the model lists. Saved choices are kept.");
}

export async function saveSettings(
  revision: string,
  changes: SettingsChanges,
): Promise<SettingsOutcome> {
  const { data, error, response } = await api.PATCH("/api/admin/settings", {
    body: { revision, changes },
  });
  if (data) return { kind: "saved", settings: data };
  const refusal = error as Refusal | undefined;
  if (response.status === 409 && refusal?.kind === "conflict")
    return { kind: "conflict", message: refusal.message };
  if (response.status === 422 && refusal?.kind === "invalid")
    return { kind: "invalid", message: refusal.message, fieldErrors: refusal.field_errors ?? {} };
  throw new Error("Could not save settings.yaml");
}
