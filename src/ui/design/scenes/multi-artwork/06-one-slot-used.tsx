import { ArtworkEditorScreen } from "../../screens/multiArtwork/ArtworkEditorScreen";
import { colours, common, designs } from "./_fixtures.ts";

export const meta = {
  title: "Artwork — only one base design used",
  viewport: "laptop",
  description: "Partial pair that can deploy (no light shirts sold), with the warning that one design may be all it needs.",
};

export default function Frame() {
  return (
    <ArtworkEditorScreen
      {...common}
      base={{ mode: "light-dark", light: null, dark: designs.lightInk }}
      colours={colours.map((c) => (c.tone === "light" ? { ...c, enabled: false } : c))}
      previewed="navy"
    />
  );
}
