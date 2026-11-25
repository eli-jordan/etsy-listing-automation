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

/** `/admin?section=backup&page=setup`: the address of a section, so a link
 * (the backup banner's Open Backup) can open it. Connected shops is bare. */
export function address(section: Section, page?: BackupPage): string {
  if (section === "connected") return "?";
  return page === "setup" ? `?section=${section}&page=setup` : `?section=${section}`;
}

/** The section a swipe moves to: left is the next one, right the one
 * before, and nothing past either end. */
export function adjacentSection(section: Section, direction: "left" | "right"): Section | null {
  const index = SECTIONS.indexOf(section) + (direction === "left" ? 1 : -1);
  return SECTIONS[index] ?? null;
}

/** Backup's two pages once it is set up, nested under it. */
export const BACKUP_PAGES = [
  ["status", "Status and history"],
  ["setup", "Setup"],
] as const;
