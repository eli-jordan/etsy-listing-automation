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

/** The domain questions about a `media:` entry (its name, kind, picture and
 * source file), layered over the api modules' one-per-endpoint URL builders. */

export type PictureSize = "tile" | "full";

export function refName(ref: string): string {
  const file = ref.split("/").pop() ?? ref;
  return file.replace(/\.[^.]+$/, "");
}

function commonMediaPath(ref: string): string {
  const prefix = "common-media/";
  return ref.startsWith(prefix) ? ref.slice(prefix.length) : ref;
}

function isListingLocal(ref: string): boolean {
  return ref.startsWith("./");
}

/** Whether an entry is a picture or a clip -- `core/config/media.py`'s
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
  /** Each template's saved-position signature (ADR-0058). */
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

/** Whose directory a `./` ref is resolved against (ADR-0047). `copies`: an unsaved
 * listing template's planned `./assets/` refs, each mapped to the ref `name` keeps it under. */
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
  const name = commonMediaPath(ref);
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

/** The server's photo path wins: it knows vendor packs' `{template}-{colour}.png`. */
export function scenePath(
  template: TemplateSummary | undefined,
  templateName: string,
  colour: string | null,
): string {
  const served = template?.photos.find((p) => (p.colour ?? null) === colour);
  if (served !== undefined) return served.file;
  return `mockup-templates/${templateName}/${colour ?? "scene"}.png`;
}
