/** The settled tag rules (`docs/ui-listing-seo-interactions.md` section 4),
 * factored out so the hook that applies a toggle and the drawer that renders
 * a suggestion's disabled state agree on exactly one definition of "full":
 * a tag already selected can always be removed; a new one can be added only
 * while fewer than 13 are selected. */
export const MAX_TAGS = 13;

export function canToggleTag(currentTags: readonly string[], tag: string): boolean {
  return currentTags.includes(tag) || currentTags.length < MAX_TAGS;
}
