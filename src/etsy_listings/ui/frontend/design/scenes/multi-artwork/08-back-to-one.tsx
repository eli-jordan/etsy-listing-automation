import { ArtworkEditorScreen } from "../../screens/multiArtwork/ArtworkEditorScreen";
import { colours, common, designs, lightDark, withOwn } from "./_fixtures.ts";

export const meta = {
  title: "Artwork — back to one design",
  viewport: "laptop",
  description: "Pressing Link on an unlinked pair asks which design every shirt should print; nothing changes until one is picked.",
};

export default function Frame() {
  return (
    <ArtworkEditorScreen
      {...common}
      base={lightDark}
      colours={withOwn(colours, "moss", designs.moss)}
      previewed="black"
      leaving
    />
  );
}
