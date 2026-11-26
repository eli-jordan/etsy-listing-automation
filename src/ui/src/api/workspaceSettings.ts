import { api } from "./client";
import { type Refusal, refusalOf } from "./refusal";
import type { components } from "./schema";

export type WorkspaceSettings = components["schemas"]["WorkspaceSettingsResponse"];
export type SettingsChanges = components["schemas"]["WorkspaceSettingsChanges"];
export type ProviderPreference = components["schemas"]["AiProviderSettings"];
export type ModelCatalogs = components["schemas"]["ModelCatalogs"];
type RefusalBody = components["schemas"]["SettingsSaveRefusal"];
export type SettingsOutcome = { kind: "saved"; settings: WorkspaceSettings } | Refusal;

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
  const { data, error } = await api.PATCH("/api/admin/settings", {
    body: { revision, changes },
  });
  if (data) return { kind: "saved", settings: data };
  const refusal = refusalOf(error);
  if (refusal) return refusal;
  throw new Error("Could not save settings.yaml");
}

export type TemplatePositionLimits = WorkspaceSettings["template_positions"];
export type TemplatePositionImpact = components["schemas"]["TemplatePositionImpactResponse"];

export async function getTemplatePositionImpact(
  limits: TemplatePositionLimits,
): Promise<TemplatePositionImpact> {
  const { data, error } = await api.POST("/api/admin/settings/template-positions/impact", {
    body: { limits },
  });
  if (data) return data;
  const refusal = error as RefusalBody | undefined;
  throw new Error(refusal?.message ?? "Could not check saved positions");
}
