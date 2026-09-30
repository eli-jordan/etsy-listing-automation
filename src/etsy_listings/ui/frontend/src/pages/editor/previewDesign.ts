import type { Artwork } from "../../media";

/** The design a listing template is being looked at through (UI doc §3):
 * one of the calibrator's test designs (A19) by its library id, or a
 * workspace design. Component state in `ListingEditorShell`, never part of
 * the document -- a listing template has no artwork, and each listing in a
 * batch gets its own. */
export type PreviewDesign =
  { kind: "test"; id: string } | { kind: "design"; name: string; file: string };

/** What every listing-template editor opens on (spec, *Completeness and
 * editing*: "`bundled-grid` is the default on each load"). */
export const DEFAULT_PREVIEW: PreviewDesign = { kind: "test", id: "bundled-grid" };

/** What the tabs composite for a preview design. */
export function previewArtwork(preview: PreviewDesign): Artwork {
  return preview.kind === "test" ? { testDesign: preview.id } : preview.name;
}

export function samePreview(a: PreviewDesign, b: PreviewDesign): boolean {
  if (a.kind === "test") return b.kind === "test" && a.id === b.id;
  return b.kind === "design" && a.name === b.name;
}
