import { isInMedia, mediaKind, missingColours } from "../../media";
import type { MediaEntry, TemplateMediaEntry } from "../../types";

/**
 * Pure patch builders for a listing's images: each returns the patch to send,
 * or `null` when there is nothing to change.
 */

export interface MediaState {
  media: readonly MediaEntry[];
  colors: readonly string[];
  etsy: { variation_images?: string | null };
}

/** Etsy's ceiling on listing images, apart from videos; mirrors `config/media.py`'s `MAX_IMAGES`. */
export const MAX_IMAGES = 20;

/** Etsy's ceiling on listing videos, `config/media.py`'s `MAX_VIDEOS`. */
export const MAX_VIDEOS = 2;

export function roomLeft(media: readonly MediaEntry[]): number {
  return Math.max(0, MAX_IMAGES - count(media, "image"));
}

type Patch = Record<string, unknown>;

export function toggleEntry(
  detail: MediaState,
  template: string,
  colour: string | null,
): Patch | null {
  if (isInMedia(detail.media, template, colour)) {
    return settled(
      detail.media.filter(
        (m) => typeof m === "string" || m.template !== template || (m.colour ?? null) !== colour,
      ),
    );
  }
  if (roomLeft(detail.media) === 0) return null;
  return { media: [...detail.media, { template, colour }] };
}

export function toggleFile(detail: MediaState, ref: string): Patch | null {
  if (detail.media.includes(ref)) {
    return settled(detail.media.filter((m) => m !== ref));
  }
  if (mediaKind(ref) === "image") {
    if (roomLeft(detail.media) === 0) return null;
    return { media: [...detail.media, ref] };
  }
  const videos = count(detail.media, "video");
  if (videos >= MAX_VIDEOS || count(detail.media, "image") === 0) return null;
  if (videos > 0) return { media: [...detail.media, ref] };
  return { media: [...detail.media.slice(0, 1), ref, ...detail.media.slice(1)] };
}

export function addEveryMissingColour(detail: MediaState, template: string): Patch | null {
  const additions = entriesForMissing(detail, template);
  if (additions.length === 0) return null;
  return { media: [...detail.media, ...additions] };
}

export function toggleSwatchSource(detail: MediaState, template: string): Patch {
  if (detail.etsy.variation_images === template) {
    return { etsy: { variation_images: null } };
  }
  return {
    media: [...detail.media, ...entriesForMissing(detail, template)],
    etsy: { variation_images: template },
  };
}

export function removeAt(detail: MediaState, index: number): Patch | null {
  return settled(detail.media.filter((_, i) => i !== index));
}

export function reorder(detail: MediaState, from: number, to: number): Patch | null {
  const next = moved(detail.media, from, to);
  return next === null ? null : { media: next };
}

export function canReorder(media: readonly MediaEntry[], from: number, to: number): boolean {
  return moved(media, from, to) !== null;
}

function moved(media: readonly MediaEntry[], from: number, to: number): MediaEntry[] | null {
  const entry = media[from];
  if (from === to || entry === undefined) return null;
  const featured = media[1];
  const pinned =
    featured !== undefined && mediaKind(featured) === "video" && mediaKind(entry) === "image";
  if (!pinned || to === 1) {
    const next = spliced(media, from, to);
    return fitsGallery(next) ? next : null;
  }
  const next = movedAroundFeaturedVideo(media, featured, from, to);
  return fitsGallery(next) ? next : null;
}

function movedAroundFeaturedVideo(
  media: readonly MediaEntry[],
  featured: MediaEntry,
  from: number,
  to: number,
): MediaEntry[] {
  const rest = media.filter((_, i) => i !== 1);
  const shift = (i: number) => (i > 1 ? i - 1 : i);
  const [thumbnail, ...after] = spliced(rest, shift(from), shift(to));
  return [thumbnail as MediaEntry, featured, ...after];
}

function spliced(media: readonly MediaEntry[], from: number, to: number): MediaEntry[] {
  const next = [...media];
  const [entry] = next.splice(from, 1);
  next.splice(to, 0, entry as MediaEntry);
  return next;
}

/** `config/listing.py`'s `_check_gallery`, order rules only: a move changes no count. */
function fitsGallery(media: readonly MediaEntry[]): boolean {
  if (media.length > 0 && mediaKind(media[0] as MediaEntry) === "video") return false;
  if (count(media, "video") === 0) return true;
  return media[1] !== undefined && mediaKind(media[1]) === "video";
}

function entriesForMissing(detail: MediaState, template: string): TemplateMediaEntry[] {
  return missingColours(detail.media, detail.colors, template)
    .slice(0, roomLeft(detail.media))
    .map((colour) => ({ template, colour }));
}

function count(media: readonly MediaEntry[], kind: "image" | "video"): number {
  return media.filter((m) => mediaKind(m) === kind).length;
}

export function settleGallery(media: readonly MediaEntry[]): MediaEntry[] | null {
  const firstVideo = media.findIndex((m) => mediaKind(m) === "video");
  if (firstVideo === -1) return [...media];
  const firstImage = media.findIndex((m) => mediaKind(m) === "image");
  if (firstImage === -1) return null;
  const thumbnail = media[firstImage] as MediaEntry;
  const rest = media.filter((_, i) => i !== firstImage);
  const featured = rest.findIndex((m) => mediaKind(m) === "video");
  const video = rest[featured] as MediaEntry;
  return [thumbnail, video, ...rest.filter((_, i) => i !== featured)];
}

function settled(media: readonly MediaEntry[]): Patch | null {
  const next = settleGallery(media);
  return next === null ? null : { media: next };
}
