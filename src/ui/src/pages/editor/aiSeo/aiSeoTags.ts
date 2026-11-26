export const MAX_TAGS = 13;

export function canToggleTag(currentTags: readonly string[], tag: string): boolean {
  return currentTags.includes(tag) || currentTags.length < MAX_TAGS;
}
