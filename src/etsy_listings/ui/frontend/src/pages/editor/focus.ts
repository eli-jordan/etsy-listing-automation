import {
  isInMedia,
  mediaKind,
  mediaLabel,
  pictureFor,
  refName,
  scenePath,
  templatePicture,
} from "../../media";
import type { Issue, MediaFileSummary, ListingDetail, TemplateSummary } from "../../types";

/**
 * What the Listing Images tab's preview pane is pointing at, and everything
 * that follows from it.
 *
 * A focus is one of the two things `media:` can hold -- but it is *not* a
 * `MediaEntry`, because the locator can point the preview at something the
 * listing has not taken yet. That distinction is the whole reason this is its
 * own module: "is what I am looking at actually in the listing?" is the
 * question the Add/Remove button, the lightbox and the reel's highlight all
 * turn on, and it was answered three separate times inline.
 */

/** For a template, a `null` colour means its fixed scene, which is also what a
 * `multiple`/`single` template always is. */
export type Focus =
  | { kind: "template"; template: string; colour: string | null }
  | { kind: "file"; asset: MediaFileSummary };

/** Everything the preview pane and its foot need, for one focus. */
export interface FocusView {
  title: string;
  /** The file it would upload, or render from -- the same question either way,
   * and the reason the foot shows a path at all. */
  path: string;
  picture: string;
  /** A video is previewed by a playable `<video>`, an image by an `<img>`
   * (PRD 72). */
  kind: "image" | "video";
  /** What the listing's check says about this one file -- a video's sound
   * note, a clip too short -- so the pane showing it says it too. */
  notes: Issue[];
  inListing: boolean;
  /** Where it sits in the reel, or `-1` when it is something the locator is
   * offering that the listing has not taken yet. Such a thing is not in the
   * carousel at all, so clicking it opens nothing -- adding it first is one
   * click away and is what the pane's own button is for. */
  reelIndex: number;
}

export function viewFocus(
  focus: Focus,
  detail: ListingDetail,
  templates: readonly TemplateSummary[],
  design: string | null,
): FocusView {
  if (focus.kind === "file") {
    const ref = focus.asset.ref;
    return {
      title: refName(ref),
      path: focus.asset.file,
      picture: pictureFor(ref, design, "full", detail.name || null),
      kind: mediaKind(ref),
      // `check_videos` places each of its issues at the ref it is about.
      notes: detail.issues.filter((issue) => issue.where === `Listing Images › ${ref}`),
      inListing: detail.media.includes(focus.asset.ref),
      reelIndex: detail.media.indexOf(focus.asset.ref),
    };
  }
  const summary = templates.find((t) => t.name === focus.template);
  return {
    title: mediaLabel({ template: focus.template, colour: focus.colour }),
    path: scenePath(summary, focus.template, focus.colour),
    picture: templatePicture(focus.template, focus.colour, design),
    kind: "image",
    notes: [],
    inListing: isInMedia(detail.media, focus.template, focus.colour),
    reelIndex: detail.media.findIndex(
      (entry) =>
        typeof entry !== "string" &&
        entry.template === focus.template &&
        (entry.colour ?? null) === focus.colour,
    ),
  };
}
