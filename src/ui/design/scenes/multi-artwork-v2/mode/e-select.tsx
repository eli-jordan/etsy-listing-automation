import { ArtworkEditorScreen } from "../_snapshot/_ArtworkEditorScreen";
import { colours, common, designs } from "../_fixtures.ts";

export const meta = {
  title: "Mode switch — E · dropdown · v2",
  viewport: "laptop",
  description: "Option E: a compact dropdown on the head line - Same design on every shirt / Different designs on light and dark shirts.",
};

export default function Frame() {
  return (
    <ArtworkEditorScreen
      {...common}
      modeControl="select"
      base={{ mode: "one", design: designs.hike }}
      colours={colours}
      previewed="black"
    />
  );
}
