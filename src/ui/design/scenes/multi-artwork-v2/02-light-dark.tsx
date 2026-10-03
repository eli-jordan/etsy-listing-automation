import { ArtworkEditorScreen } from "./_snapshot/_ArtworkEditorScreen";
import { colours, common, lightDark } from "./_fixtures.ts";

export const meta = {
  title: "Artwork — light and dark shirts · v2",
  viewport: "laptop",
  description: "Both base designs chosen; each Variants row shows which design that colour prints, on its own cloth.",
};

export default function Frame() {
  return <ArtworkEditorScreen {...common} base={lightDark} colours={colours} previewed="black" />;
}
