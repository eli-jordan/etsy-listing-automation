import {
  type Artwork,
  type MediaOwner,
  mediaKind,
  mediaLabel,
  pictureFor,
  refName,
  scenePath,
  templatePicture,
} from "../../media";
import type {
  Issue,
  MediaEntry,
  MediaFileSummary,
  ListingDetail,
  TemplateSummary,
} from "../../types";

/**
 * What the Listing Images tab's preview pane is pointing at. Not a
 * `MediaEntry`: the locator can point the preview at something the listing has
 * not taken yet.
 */

/** A template's `null` colour is its fixed scene, as every `multiple`/`single` template's is. */
export type Focus =
  | { kind: "template"; template: string; colour: string | null }
  | { kind: "file"; asset: MediaFileSummary };

export type FocusRef =
  { kind: "template"; template: string; colour: string | null } | { kind: "file"; ref: string };

export function focusRef(focus: Focus): FocusRef {
  return focus.kind === "file" ? { kind: "file", ref: focus.asset.ref } : focus;
}

export function isFocusRef(value: unknown): value is FocusRef {
  if (typeof value !== "object" || value === null) return false;
  const ref = value as Record<string, unknown>;
  if (ref.kind === "file") return typeof ref.ref === "string";
  return (
    ref.kind === "template" &&
    typeof ref.template === "string" &&
    (ref.colour === null || typeof ref.colour === "string")
  );
}

export function restoreFocus(
  ref: FocusRef | null,
  templates: readonly TemplateSummary[],
  files: readonly MediaFileSummary[],
): Focus | null {
  if (ref === null) return null;
  if (ref.kind === "file") {
    const asset = files.find((file) => file.ref === ref.ref);
    return asset === undefined ? null : { kind: "file", asset };
  }
  const summary = templates.find((template) => template.name === ref.template);
  if (summary === undefined) return null;
  return ref.colour === null || hasColour(summary, ref.colour) ? ref : null;
}

/** Whether a template has a photo for the listing's bare colour slug. A
 * template whose photos share a filename prefix (`{template}-{colour}.png`)
 * lists each whole stem as its colour, so `white` is there as
 * `{template}-white` (see `LocatorTemplate`'s chips). */
function hasColour(summary: TemplateSummary, colour: string): boolean {
  return summary.colours.includes(colour) || summary.colours.includes(`${summary.name}-${colour}`);
}

export function firstFocus(
  media: readonly MediaEntry[],
  templates: readonly TemplateSummary[],
  files: readonly MediaFileSummary[],
): Focus | null {
  const first = media[0];
  if (first === undefined) return null;
  const ref: FocusRef =
    typeof first === "string"
      ? { kind: "file", ref: first }
      : { kind: "template", template: first.template, colour: first.colour ?? null };
  return restoreFocus(ref, templates, files);
}

export interface FocusView {
  title: string;
  path: string;
  picture: string;
  kind: "image" | "video";
  notes: Issue[];
  /** Null for something the locator offers that the listing has not taken. */
  reelIndex: number | null;
}

function found(index: number): number | null {
  return index >= 0 ? index : null;
}

export function viewFocus(
  focus: Focus,
  detail: ListingDetail,
  templates: readonly TemplateSummary[],
  scene: Artwork | null,
  owner: MediaOwner | string | null = detail.name || null,
): FocusView {
  if (focus.kind === "file") {
    const ref = focus.asset.ref;
    return {
      title: refName(ref),
      path: focus.asset.file,
      picture: pictureFor(ref, scene, "full", owner),
      kind: mediaKind(ref),
      // `check_videos` places each of its issues at the ref it is about.
      notes: detail.issues.filter((issue) => issue.where === `Listing Images › ${ref}`),
      reelIndex: found(detail.media.indexOf(focus.asset.ref)),
    };
  }
  const summary = templates.find((t) => t.name === focus.template);
  return {
    title: mediaLabel({ template: focus.template, colour: focus.colour }),
    path: scenePath(summary, focus.template, focus.colour),
    picture: templatePicture(focus.template, focus.colour, scene),
    kind: "image",
    notes: [],
    reelIndex: found(
      detail.media.findIndex(
        (entry) =>
          typeof entry !== "string" &&
          entry.template === focus.template &&
          (entry.colour ?? null) === focus.colour,
      ),
    ),
  };
}
