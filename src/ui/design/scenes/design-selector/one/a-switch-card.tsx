import { ArtworkEditorScreen } from "../../../screens/multiArtwork/ArtworkEditorScreen";
import { colours, common, designs } from "../_fixtures.ts";
import { StripA } from "../_StripA";

export const meta = {
  title: "A · switch card — one design",
  viewport: "laptop",
  description: "One card with a switch on its right edge; switching on splits the card into light and dark halves in place. Each half is a drop target.",
};

export default function Frame() {
  return (
    <ArtworkEditorScreen
      {...common}
      base={{ mode: "one", design: designs.hike }}
      colours={colours}
      previewed="black"
      strip={(api) => <StripA api={api} />}
    />
  );
}
