/** The label rules, so the Labels bar can explain them before anything is
 * sent. The server applies them on save (`core/config/template_labels.py`);
 * these messages repeat its words, and it stays the one that decides. */

export const MAX_LABELS = 10;
const MAX_LABEL_LENGTH = 30;

export const LABEL_CAP_MESSAGE = `Templates hold up to ${MAX_LABELS} labels`;

/** The text as it would be saved. */
export function tidiedLabel(text: string): string {
  return text.trim().toLowerCase().replace(/\s+/g, " ");
}

/** Why `label`, already tidied, cannot be saved; null when it can. */
export function labelRefusal(label: string): string | null {
  if (label.length > MAX_LABEL_LENGTH) return `Labels can be up to ${MAX_LABEL_LENGTH} characters`;
  if (!/^[a-z0-9 :-]+$/.test(label)) return "Letters, numbers, spaces, hyphens and colons only";
  const parts = label.split(":");
  if (parts.length > 2 || parts.some((part) => part.trim() === "")) {
    return "Use one colon with text on both sides, like theme:christmas";
  }
  return null;
}

/** Whether a template holds every pill. A hand-edited label keeps its case, so
 * `Christmas` still counts as `christmas`. */
export function holdsLabels(labels: string[], pills: string[]): boolean {
  const held = new Set(labels.map((label) => label.toLowerCase()));
  return pills.every((pill) => held.has(pill.toLowerCase()));
}
