import { ArtworkEditorScreen } from "../../screens/multiArtwork/ArtworkEditorScreen";
import { colours, common, lightDark } from "./_fixtures.ts";

export const meta = {
  title: "Artwork — choose a design for one colour",
  viewport: "laptop",
  description: "Select different design on Moss: the library picker, thumbnails shown on moss cloth.",
};

export default function Frame() {
  return (
    <ArtworkEditorScreen
      {...common}
      base={lightDark}
      colours={colours}
      previewed="moss"
      picking={{ kind: "colour", name: "moss" }}
    />
  );
}
