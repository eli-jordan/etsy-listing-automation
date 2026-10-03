import { ArtworkEditorScreen } from "../_snapshot/_ArtworkEditorScreen";
import { colours, common, designs } from "../_fixtures.ts";

export const meta = {
  title: "Mode switch — D · linked pair · v2",
  viewport: "laptop",
  description: "Option D: always two cards joined by a link button; unlinking, or picking a different dark design, splits them.",
};

export default function Frame() {
  return (
    <ArtworkEditorScreen
      {...common}
      modeControl="linked"
      base={{ mode: "one", design: designs.hike }}
      colours={colours}
      previewed="black"
    />
  );
}
