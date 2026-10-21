import { ArtworkEditorScreen } from "./_snapshot/_ArtworkEditorScreen";
import { colours, common, designs } from "./_fixtures.ts";

export const meta = {
  title: "Artwork — design for light shirts missing · v2",
  viewport: "laptop",
  description: "Partial pair: Ivory and Natural need the empty light-shirt slot, so deploying is blocked until it is filled.",
};

export default function Frame() {
  return (
    <ArtworkEditorScreen
      {...common}
      base={{ mode: "light-dark", light: null, dark: designs.lightInk }}
      colours={colours}
      previewed="ivory"
    />
  );
}
