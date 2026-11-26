import type { ListingDetail, MediaEntry } from "../../types";
import { settleGallery } from "./mediaEdits";

/**
 * `core/config/listing.py`'s validator refuses a document whose `media[]`,
 * `design{}` or `price_overrides{}` names a colour the listing no longer
 * sells, so dropping a colour drops what depended on it, in the same patch.
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
  if (media.length !== detail.media.length) {
    patch.media = settleGallery(media) ?? [];
  }

  const design = withoutKeys(detail.design, gone);
  if (design !== null) patch.design = design;

  const prices = withoutKeys(detail.price_overrides, gone);
  if (prices !== null) patch.price_overrides = prices;

  return patch;
}

export function selectGarmentProfile(
  detail: ListingDetail,
  name: string,
  colours: string[],
): Record<string, unknown> {
  return { garment_profile: name, ...selectColours(detail, colours) };
}

function withoutKeys<T>(
  record: Record<string, T> | undefined,
  dropped: Set<string>,
): Record<string, T> | null {
  if (!record) return null;
  const entries = Object.entries(record).filter(([colour]) => !dropped.has(colour));
  if (entries.length === Object.keys(record).length) return null;
  return Object.fromEntries(entries);
}

export function mediaLostBy(detail: ListingDetail, next: string[]): number {
  const patch = selectColours(detail, next);
  const media = patch.media as MediaEntry[] | undefined;
  return media === undefined ? 0 : detail.media.length - media.length;
}
