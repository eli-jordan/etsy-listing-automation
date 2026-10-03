import { ArtworkEditorScreen } from "../../screens/multiArtwork/ArtworkEditorScreen";
import { colours, common, lightDark } from "./_fixtures.ts";

export const meta = {
  title: "Artwork — light and dark shirts",
  viewport: "laptop",
  description: "Unlinked pair with both designs chosen; each Variants row shows which design that colour prints, on its own cloth.",
};

export default function Frame() {
  return <ArtworkEditorScreen {...common} base={lightDark} colours={colours} previewed="black" />;
}
