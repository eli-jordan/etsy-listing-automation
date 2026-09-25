import { templateDesignPreviewUrl, templatePhotoUrl, templateThumbnailUrl } from "./api/calibrator";
import { commonMediaFileUrl, commonMediaThumbnailUrl } from "./api/listings";
import type { MediaEntry, TemplateSummary } from "./types";

/**
 * What `media:` holds, and what it looks like.
 *
 * `media:` carries two shapes in one list (`config/listing.py`'s `MediaEntry`):
 * a `{template, colour}` entry the tool renders, and a bare path to a shared
 * asset under `common-media/` that is uploaded as-is. Every question about
 * either one -- what is it called, is it already in the listing, which picture
 * shows it, which file on disk does it come from -- is answered here.
 *
 * It exists because those answers were spread across whichever tab first
 * needed them. Six near-identical URL builders lived in two api modules;
 * "strip the directory and the `.png`" was written three times with three
 * different regexes; and "composite the design if there is one, otherwise show
 * the bare photo" was written twice, in `ImagesTab` and `VariantsTab`, with
 * *different* fallback orders. A component that wants a picture of something
 * now needs to know one function, not which of two api modules to import from
 * and which of five builders applies.
 *
 * The api modules keep their builders: those are the HTTP surface, one function
 * per endpoint, and this is the domain question layered over them.
 */

/** How big a picture the caller is asking for.
 *
 * `tile` is the 160px-capped thumbnail a row of them is picked from; `full` is
 * the photo's own resolution, for the one image being *judged* -- a preview
 * pane or a lightbox. They are different endpoints, not a query parameter, so
 * this is the one place the choice is made.
 */
export type PictureSize = "tile" | "full";

/** A shared asset's name, from the bare ref a listing stores.
 *
 * Filename-derived rather than looked up, so a reel tile still labels itself
 * when the file has been deleted from `common-media/` since the listing named
 * it. One implementation: `DesignSelect` and the reel each had their own.
 */
export function refName(ref: string): string {
  const file = ref.split("/").pop() ?? ref;
  return file.replace(/\.[^.]+$/, "");
}

/** A shared ref's path under `common-media/` -- what the picture endpoints
 * take. The whole path, not the stem: a shared file may be a JPEG and may sit
 * in a subdirectory (PRD 71), and only its full path says which file it is. */
function sharedName(ref: string): string {
  const prefix = "common-media/";
  return ref.startsWith(prefix) ? ref.slice(prefix.length) : ref;
}

/**
 * The one design a render can overlay -- `null` for a multi-artwork listing
 * (`on-light`/`on-dark`), where there is no single "the design" to composite,
 * which is the same case `DesignSelect` treats as read-only.
 *
 * Here rather than beside the Design strip because every caller wants it for
 * the same reason: it is the second argument to {@link pictureFor}.
 */
export function singleDesignName(design: Record<string, string>): string | null {
  const values = Object.values(design);
  if (values.length !== 1) return null;
  return refName(values[0] as string) || null;
}

/** What to call one entry, in a tile label, a lightbox caption or an aria-label. */
export function mediaLabel(entry: MediaEntry): string {
  if (typeof entry === "string") return refName(entry);
  return entry.colour ? `${entry.template} · ${entry.colour}` : entry.template;
}

/** Is this template/colour pair already in `media:`?
 *
 * `(entry.colour ?? null) === colour` rather than `==`, because a
 * `multiple`/`single` entry's absent colour and an explicit `null` are the
 * same thing and `undefined` is not.
 */
export function isInMedia(
  media: readonly MediaEntry[],
  template: string,
  colour: string | null,
): boolean {
  return media.some(
    (m) => typeof m !== "string" && m.template === template && (m.colour ?? null) === colour,
  );
}

/** Colours this listing sells that `template` has no entry for.
 *
 * Driven by `colors:`, not by the template's own photo set -- a swatch is owed
 * for every colour on sale, and one the template cannot supply is exactly what
 * the coverage warning is for.
 */
export function missingColours(
  media: readonly MediaEntry[],
  colors: readonly string[],
  template: string,
): string[] {
  return colors.filter((c) => !isInMedia(media, template, c));
}

/**
 * The picture for one thing `media:` can hold.
 *
 * A template entry is a *render*: the listing's real artwork composited onto
 * the template's saved geometry. `design` is null for a multi-artwork listing
 * (`on-light`/`on-dark`), where there is no single design to composite, and
 * that case falls back to the bare inkless photo. A shared asset is already
 * exactly the file Etsy would receive, so it is served as-is.
 *
 * At `tile` size a template entry is always the bare thumbnail, never a render:
 * a tile is picked out of a row, and running the real pipeline once per tile
 * would cost a render per listing image just to open the tab. The thumbnail
 * still takes the colour -- without it a colour-matrix set answers with the
 * same photo every time, and a reel of eight identical tiles under eight
 * different colour labels is worse than no picture at all.
 */
export function pictureFor(
  entry: MediaEntry,
  design: string | null,
  size: PictureSize = "full",
): string {
  if (typeof entry === "string") {
    const name = sharedName(entry);
    return size === "tile" ? commonMediaThumbnailUrl(name) : commonMediaFileUrl(name);
  }
  return templatePicture(entry.template, entry.colour ?? null, design, size);
}

/** The same, for a template/colour the locator is offering but the listing has
 * not taken yet -- there is no `MediaEntry` for it to be asked about. */
export function templatePicture(
  template: string,
  colour: string | null,
  design: string | null,
  size: PictureSize = "full",
): string {
  if (size === "tile") return templateThumbnailUrl(template, colour);
  if (design === null) return templatePhotoUrl(template, colour);
  return templateDesignPreviewUrl(template, design, colour);
}

/**
 * The file on disk an entry renders from, for the caption under a preview.
 *
 * Served by `GET /api/templates` (`TemplateSummary.photos`) rather than
 * composed here from PRD 7a's convention. That matters for the one layout the
 * convention does not describe: a vendor pack delivered as
 * `{template}-{colour}.png` is resolved by `Workspace.template_base_image`'s
 * trailing-segment fallback, and a caption derived from the convention alone
 * named a file that is not there.
 *
 * The plain convention is still the fallback, for a colour the server did not
 * list -- a colour the listing sells that this template has no photo for. That
 * path does not exist either, but naming the file the template *would* need is
 * the useful thing to say about a missing one.
 */
export function scenePath(
  template: TemplateSummary | undefined,
  templateName: string,
  colour: string | null,
): string {
  const served = template?.photos.find((p) => (p.colour ?? null) === colour);
  if (served !== undefined) return served.file;
  return `mockup-templates/${templateName}/${colour ?? "scene"}.png`;
}
