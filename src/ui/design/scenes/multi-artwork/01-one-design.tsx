import { ArtworkEditorScreen } from "../../screens/multiArtwork/ArtworkEditorScreen";
import { colours, common, designs } from "./_fixtures.ts";

export const meta = {
  title: "Artwork — one design",
  viewport: "laptop",
  description: "One design for every shirt: the pair is linked, so the dark-shirt card mirrors the light one; each row shows what it prints.",
};

export default function Frame() {
  return <ArtworkEditorScreen {...common} base={{ mode: "one", design: designs.hike }} colours={colours} previewed="black" />;
}
