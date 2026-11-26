import type { Artwork } from "../../media";

export type PreviewDesign =
  { kind: "test"; id: string } | { kind: "design"; name: string; file: string };

export const DEFAULT_PREVIEW: PreviewDesign = { kind: "test", id: "bundled-grid" };

export function previewArtwork(preview: PreviewDesign): Artwork {
  return preview.kind === "test" ? { testDesign: preview.id } : preview.name;
}

export function samePreview(a: PreviewDesign, b: PreviewDesign): boolean {
  if (a.kind === "test") return b.kind === "test" && a.id === b.id;
  return b.kind === "design" && a.name === b.name;
}
