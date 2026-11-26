import { templateDesignPreviewUrl, templatePhotoUrl, templateThumbnailUrl } from "./api/calibrator";
import {
  commonMediaFileUrl,
  commonMediaThumbnailUrl,
  listingMediaFileUrl,
  listingMediaThumbnailUrl,
  listingScenePreviewUrl,
} from "./api/listings";
import {
  listingTemplateMediaFileUrl,
  listingTemplateMediaThumbnailUrl,
} from "./api/listingTemplates";
import type { MediaEntry, TemplateSummary } from "./types";

/**
 * What `media:` holds, and what it looks like.
 *
 * `media:` carries two shapes in one list (`config/listing.py`'s `MediaEntry`):
 * a `{template, colour}` entry the tool renders, and a file ref uploaded
 * as-is -- a shared file under `common-media/`, or one of the listing's own
 * spelled `./…` -- which may be an image or a video. Every
 * question about either one -- what is it called, what kind is it, is it
 * already in the listing, which picture shows it, which file on disk does it
 * come from -- is answered here.
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

export type PictureSize = "tile" | "full";

/** A shared asset's name, from the bare ref a listing stores.
 *
 * Filename-derived rather than looked up, so a reel tile still labels itself
 * when the file has been deleted from `common-media/` since the listing named
 * it. One implementation: the design strip and the reel each had their own.
 */
export function refName(ref: string): string {
  const file = ref.split("/").pop() ?? ref;
  return file.replace(/\.[^.]+$/, "");
}

/** A shared ref's path under `common-media/` -- what the picture endpoints
 * take. The whole path, not the stem: a shared file may be a JPEG and may sit
 * in a subdirectory, and only its full path says which file it is. */
function sharedName(ref: string): string {
  const prefix = "common-media/";
  return ref.startsWith(prefix) ? ref.slice(prefix.length) : ref;
}

function isListingLocal(ref: string): boolean {
  return ref.startsWith("./");
}

/** Whether an entry is a picture or a clip -- `config/media.py`'s
 * `media_kind`, mirrored.
 *
 * A template entry is always an image (a render is a PNG) and a file ref is a
 * video by its extension alone, case-insensitively, since a phone names its
 * clips `IMG_1234.MOV`. Every other ref is an image: a listing whose `media:`
 * names an unknown type is refused on load, so it never reaches the browser.
 */
export function mediaKind(entry: MediaEntry): "image" | "video" {
  if (typeof entry !== "string") return "image";
  return /\.(mp4|mov)$/i.test(entry) ? "video" : "image";
}

export interface SceneSource {
  listing: string;
  version: string;
  /** A signature of each template's *saved* position (ADR-0058), added to
   * that template's version so a landed position save is a new URL too. */
  positions?: Readonly<Record<string, string>>;
}

export function sceneSource(
  listing: string,
  designVersion: string | null | undefined,
  positions?: Readonly<Record<string, string>>,
): SceneSource | null {
  if (listing === "" || designVersion === null || designVersion === undefined) return null;
  return positions === undefined
    ? { listing, version: designVersion }
    : { listing, version: designVersion, positions };
}

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

export function pictureFor(
  entry: MediaEntry,
  artwork: Artwork | null,
  size: PictureSize = "full",
  owner: MediaOwner | string | null = null,
): string {
  if (typeof entry === "string") return filePicture(entry, size, ownerOf(owner));
  return templatePicture(entry.template, entry.colour ?? null, artwork, size);
}

/** What a render composites onto a template's photo: a saved listing, each
 * layer printing the file its colour resolves to ({@link SceneSource}); or,
 * in the listing-template editor where there is no artwork (UI doc §3), one
 * design picked only to preview with -- a workspace design by name, or a
 * calibrator test design by its library id. An object for the test design so
 * the two names cannot be mistaken for each other: they name files in
 * different directories. */
export type Artwork = SceneSource | string | { testDesign: string };

/** Whose directory a `./` ref is resolved against: a listing's, or a listing
 * template's (ADR-0047) -- the one other thing that owns files of its own.
 *
 * `copies` is for a listing template not saved yet (the *name it* state, UI
 * doc §1): its `./assets/…` refs are only a plan until the save copies them,
 * so each is drawn from the ref its source (`name`) still keeps it under. */
export interface MediaOwner {
  kind: "listing" | "listing-template";
  name: string;
  copies?: Readonly<Record<string, string>>;
}

/** A bare string is a listing's name -- what every listing caller passes. */
function ownerOf(owner: MediaOwner | string | null): MediaOwner | null {
  if (owner === null || owner === "") return null;
  return typeof owner === "string" ? { kind: "listing", name: owner } : owner;
}

function ownFilePicture(owner: MediaOwner, name: string, tile: boolean): string {
  if (owner.kind === "listing-template") {
    return tile
      ? listingTemplateMediaThumbnailUrl(owner.name, name)
      : listingTemplateMediaFileUrl(owner.name, name);
  }
  return tile ? listingMediaThumbnailUrl(owner.name, name) : listingMediaFileUrl(owner.name, name);
}

/** A `./` ref with no owner (an unnamed draft has no directory) names nothing:
 * the empty string, not a URL that would 404. */
function filePicture(ref: string, size: PictureSize, owner: MediaOwner | null): string {
  const tile = size === "tile" && mediaKind(ref) === "image";
  if (isListingLocal(ref)) {
    if (owner === null) return "";
    return ownFilePicture(owner, (owner.copies?.[ref] ?? ref).slice(2), tile);
  }
  const name = sharedName(ref);
  return tile ? commonMediaThumbnailUrl(name) : commonMediaFileUrl(name);
}

export function ownedTile(entry: MediaEntry, owner: MediaOwner): string {
  return pictureFor(entry, null, "tile", owner);
}

export function templatePicture(
  template: string,
  colour: string | null,
  artwork: Artwork | null,
  size: PictureSize = "full",
): string {
  if (size === "tile") return templateThumbnailUrl(template, colour);
  if (artwork === null) return templatePhotoUrl(template, colour);
  if (typeof artwork === "string" || "testDesign" in artwork) {
    return templateDesignPreviewUrl(template, artwork, colour);
  }
  const position = artwork.positions?.[template];
  const version = position ? `${artwork.version}.${position}` : artwork.version;
  return listingScenePreviewUrl(artwork.listing, template, colour, version);
}

/**
 * The file on disk an entry renders from, for the caption under a preview.
 *
 * Served by `GET /api/templates` (`TemplateSummary.photos`) rather than
 * composed here from ADR-0004's convention. That matters for the one layout the
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
