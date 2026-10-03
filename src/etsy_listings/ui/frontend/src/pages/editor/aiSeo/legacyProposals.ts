/**
 * The browser-local proposals this app kept before ADR-0049 moved them to the
 * server: the pending proposal per workspace and listing, and the
 * `generated_at` of the last one each listing received. The spec (*Durable
 * AI proposals*) discards them rather than migrating them, so `main.tsx`
 * calls this once on load and nothing reads either prefix any more.
 */

const LEGACY_PREFIXES = ["ai-seo-proposal:", "ai-seo-received:"];

export function purgeLegacyProposals(storage: Storage): void {
  const doomed: string[] = [];
  for (let index = 0; index < storage.length; index++) {
    const key = storage.key(index);
    if (key !== null && LEGACY_PREFIXES.some((prefix) => key.startsWith(prefix))) {
      doomed.push(key);
    }
  }
  for (const key of doomed) storage.removeItem(key);
}
