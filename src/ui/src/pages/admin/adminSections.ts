import type { BackupPage } from "./backup/BackupSection";
import type { SettingsSection } from "./SettingsPanel";

/**
 * Admin's sections, in the order the desktop list shows them and the phone
 * chips run (and swipe) through them.
 */

export type Section = "connected" | "defaults" | SettingsSection;

export const SECTIONS: readonly Section[] = ["connected", "defaults", "ai", "rendering", "backup"];

export const SECTION_LABELS: Record<Section, string> = {
  connected: "Connected shops",
  defaults: "Listing defaults",
  ai: "AI",
  rendering: "Template rendering",
  backup: "Backup",
};

export const isSettings = (section: Section): section is SettingsSection =>
  section === "ai" || section === "rendering" || section === "backup";

export function address(section: Section, page?: BackupPage): string {
  if (section === "connected") return "?";
  return page === "setup" ? `?section=${section}&page=setup` : `?section=${section}`;
}

export const BACKUP_PAGES = [
  ["status", "Status and history"],
  ["setup", "Setup"],
] as const;
