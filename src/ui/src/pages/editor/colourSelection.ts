import type { ListingDetail, MediaEntry } from "../../types";

/**
 * Changing which colours a listing sells, and everything that has to move
 * with it.
 *
 * `colors:` is not a field on its own -- three others are keyed by it, and
 * `config/listing.py`'s validator refuses a document where any of them names
 * a colour the listing no longer sells:
 *
 * * `media[]` -- a `{template, colour}` entry pointing at a dropped colour
 * * `artwork{}` -- a per-colour ink override
 * * `price_overrides{}` -- a per-colour price
 *
 * Sending `colors` alone is what made the Variants tab's switch appear to
 * re-enable itself the instant it was turned off: the PATCH failed validation
 * server-side, which is answered with a **200** carrying `field_errors` and
 * the listing *unchanged* (so inline validation never needs a status branch)
 * -- and the editor then rendered that unchanged listing, switch back on, with
 * the reason buried in a field the Variants tab does not show.
 *
 * So dropping a colour drops what depended on it, in the same patch. That is
 * a real edit, not a workaround: a mockup of a colour the listing does not
 * sell is an image Etsy would be sent for a variant that does not exist.
 */
export function selectColours(detail: ListingDetail, next: string[]): Record<string, unknown> {
  const kept = new Set(next);
  const dropped = detail.colors.filter((colour) => !kept.has(colour));
  const patch: Record<string, unknown> = { colors: next };
  if (dropped.length === 0) return patch;

  const gone = new Set(dropped);
  const media = detail.media.filter(
    (entry: MediaEntry) => typeof entry === "string" || !entry.colour || !gone.has(entry.colour),
  );
  if (media.length !== detail.media.length) patch.media = media;

  const artwork = withoutKeys(detail.artwork, gone);
  if (artwork !== null) patch.artwork = artwork;

  const prices = withoutKeys(detail.price_overrides, gone);
  if (prices !== null) patch.price_overrides = prices;

  return patch;
}

/** Picking a garment profile, and enabling every colour it classifies.

 * The Variants tab passes `Object.keys(profile.colors)`. Going through
 * `selectColours` is what drops mockups of colours the new garment does
 * not sell, the same cascade a Dark/Light switch already uses.
 */
export function selectGarmentProfile(
  detail: ListingDetail,
  name: string,
  colours: string[],
): Record<string, unknown> {
  return { garment_profile: name, ...selectColours(detail, colours) };
}

/** ``record`` without the dropped colours, or ``null`` when it had none of
 * them -- so the caller can leave the field out of the patch entirely rather
 * than rewriting it to itself. */
function withoutKeys<T>(
  record: Record<string, T> | undefined,
  dropped: Set<string>,
): Record<string, T> | null {
  if (!record) return null;
  const entries = Object.entries(record).filter(([colour]) => !dropped.has(colour));
  if (entries.length === Object.keys(record).length) return null;
  return Object.fromEntries(entries);
}

/** How many `media:` entries would be discarded by narrowing to ``next`` --
 * what the tab warns with before a bulk Dark/Light switch throws away a reel
 * somebody built by hand. */
export function mediaLostBy(detail: ListingDetail, next: string[]): number {
  const patch = selectColours(detail, next);
  const media = patch.media as MediaEntry[] | undefined;
  return media === undefined ? 0 : detail.media.length - media.length;
}
