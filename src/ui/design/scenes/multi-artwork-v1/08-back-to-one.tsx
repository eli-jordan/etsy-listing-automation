import { ArtworkEditorScreen } from "./_snapshot/_ArtworkEditorScreen";
import { colours, common, designs, lightDark, withOwn } from "./_fixtures.ts";

export const meta = {
  title: "Artwork — back to one design · v1",
  viewport: "laptop",
  description: "Choosing One design for all shirts from light/dark asks which base design to keep; nothing changes until one is picked.",
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
