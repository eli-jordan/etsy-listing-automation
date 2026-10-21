import { ArtworkEditorScreen } from "../../screens/multiArtwork/ArtworkEditorScreen";
import { colours, common, designs, lightDark, withOwn } from "./_fixtures.ts";

export const meta = {
  title: "Artwork — colour with its own design",
  viewport: "laptop",
  description: "Moss prints its own design; the row, the strip and the preview card say so and offer Use automatic design.",
};

export default function Frame() {
  return (
    <ArtworkEditorScreen
      {...common}
      base={lightDark}
      colours={withOwn(colours, "moss", designs.moss)}
      previewed="moss"
    />
  );
}
