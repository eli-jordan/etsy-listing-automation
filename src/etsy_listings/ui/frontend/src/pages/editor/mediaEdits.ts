import { isInMedia, missingColours } from "../../media";
import type { MediaEntry, TemplateMediaEntry } from "../../types";

/**
 * Every rule about *changing* a listing's images, as a patch.
 *
 * Each function takes the listing and returns the patch to send, or `null` when
 * there is nothing to change. No component state, no DOM, no fetch -- so the
 * rules can be tested by calling them, which is the whole reason they are not
 * closures inside `ImagesTab` any more. The one that matters most was the
 * hardest to reach that way: `toggleSwatchSource` is PRD 56's gate, and it was
 * a callback three levels inside a 733-line component.
 */

/**
 * The three fields of a listing these rules read.
 *
 * Structural, so a `ListingDetail` is one without being converted -- but a
 * *test* is three fields rather than the twenty-eight the wire response
 * carries. That was the tell that these rules were in the wrong place: to
 * check that the twenty-first image is refused, a test had to invent a
 * garment profile, a price table and an Etsy section first.
 */
export interface MediaState {
  media: readonly MediaEntry[];
  colors: readonly string[];
  etsy: { variation_images?: string | null };
}

/** Etsy's ceiling on listing images, mirrored from `config/listing.py`'s
 * `MAX_MEDIA_ENTRIES`. Shown, not enforced -- the server refuses past it. */
export const MAX_MEDIA = 20;

/** How many more entries will fit before Etsy's ceiling. */
export function roomLeft(media: readonly MediaEntry[]): number {
  return Math.max(0, MAX_MEDIA - media.length);
}

type Patch = Record<string, unknown>;

/** Add a template/colour to the reel, or take it out again.
 *
 * A removal is always allowed; an addition stops at the ceiling rather than
 * writing a twenty-first entry the server would refuse.
 */
export function toggleEntry(
  detail: MediaState,
  template: string,
  colour: string | null,
): Patch | null {
  if (isInMedia(detail.media, template, colour)) {
    return {
      media: detail.media.filter(
        (m) => typeof m === "string" || m.template !== template || (m.colour ?? null) !== colour,
      ),
    };
  }
  if (roomLeft(detail.media) === 0) return null;
  return { media: [...detail.media, { template, colour }] };
}

/** A shared asset is a bare string in `media:`, not a `{template, colour}`
 * entry -- the same list, two shapes (`config/listing.py`'s `MediaEntry`). */
export function toggleShared(detail: MediaState, ref: string): Patch | null {
  if (detail.media.includes(ref)) {
    return { media: detail.media.filter((m) => m !== ref) };
  }
  if (roomLeft(detail.media) === 0) return null;
  return { media: [...detail.media, ref] };
}

/** Fill in every colour this listing sells that `template` has no entry for,
 * as far as the ceiling allows. */
export function addEveryMissingColour(detail: MediaState, template: string): Patch | null {
  const additions = entriesForMissing(detail, template);
  if (additions.length === 0) return null;
  return { media: [...detail.media, ...additions] };
}

/**
 * Point Etsy's colour swatches at this template, or turn them off.
 *
 * Turning it on also adds the colours it lacks: PRD 56's gate
 * (`EtsyMediaStage.desired()`) refuses a `variation_images` template whose
 * colours the media does not carry, so naming one without filling it in would
 * write a listing the engine then refuses to apply. Switching *from* another
 * template is the same move -- there is one swatch source, so setting this one
 * clears that one by definition.
 */
export function toggleSwatchSource(detail: MediaState, template: string): Patch {
  if (detail.etsy.variation_images === template) {
    return { etsy: { variation_images: null } };
  }
  return {
    media: [...detail.media, ...entriesForMissing(detail, template)],
    etsy: { variation_images: template },
  };
}

export function removeAt(detail: MediaState, index: number): Patch {
  return { media: detail.media.filter((_, i) => i !== index) };
}

/** Move a reel tile. The reel's order is the order Etsy shows the images in,
 * so this is a product decision the user makes by dragging, not a display
 * detail. */
export function reorder(detail: MediaState, from: number, to: number): Patch | null {
  if (from === to) return null;
  const next = [...detail.media];
  const moved = next[from];
  if (moved === undefined) return null;
  next.splice(from, 1);
  next.splice(to, 0, moved);
  return { media: next };
}

function entriesForMissing(detail: MediaState, template: string): TemplateMediaEntry[] {
  return missingColours(detail.media, detail.colors, template)
    .slice(0, roomLeft(detail.media))
    .map((colour) => ({ template, colour }));
}
