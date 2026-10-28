import { ArtworkEditorScreen } from "../../../screens/multiArtwork/ArtworkEditorScreen";
import { colours, common, designs } from "../_fixtures.ts";
import { StripD } from "../_StripD";

export const meta = {
  title: "D · drop picks the scope — file held over it",
  viewport: "laptop",
  description: "A light and a dark shirt wearing their prints; holding a file over it opens all / light-only / dark-only drop targets, so dropping can split.",
};

export default function Frame() {
  return (
    <ArtworkEditorScreen
      {...common}
      base={{ mode: "one", design: designs.hike }}
      colours={colours}
      previewed="black"
      strip={(api) => <StripD api={api} start={{ dragging: "dark" }} />}
    />
  );
}
