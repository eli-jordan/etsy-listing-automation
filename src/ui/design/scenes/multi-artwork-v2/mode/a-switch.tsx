import { ArtworkEditorScreen } from "../_snapshot/_ArtworkEditorScreen";
import { colours, common, designs } from "../_fixtures.ts";

export const meta = {
  title: "Mode switch — A · switch · v2",
  viewport: "laptop",
  description: "Option A: a labelled on/off switch on the strip's head line, matching the colour switches below.",
};

export default function Frame() {
  return (
    <ArtworkEditorScreen
      {...common}
      modeControl="switch"
      base={{ mode: "one", design: designs.hike }}
      colours={colours}
      previewed="black"
    />
  );
}
