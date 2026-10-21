import { ArtworkEditorScreen } from "../_snapshot/_ArtworkEditorScreen";
import { colours, common, designs } from "../_fixtures.ts";

export const meta = {
  title: "Mode switch — B · link · v2",
  viewport: "laptop",
  description: "Option B: no control until needed - a quiet link beside the design offers different light/dark designs.",
};

export default function Frame() {
  return (
    <ArtworkEditorScreen
      {...common}
      modeControl="link"
      base={{ mode: "one", design: designs.hike }}
      colours={colours}
      previewed="black"
    />
  );
}
