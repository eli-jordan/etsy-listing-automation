import { ArtworkEditorScreen } from "../_snapshot/_ArtworkEditorScreen";
import { colours, common, designs } from "../_fixtures.ts";

export const meta = {
  title: "Mode switch — C · in the picker · v2",
  viewport: "laptop",
  description: "Option C: the mode lives inside the Change panel, under Recent designs - invisible until a design is being changed.",
};

export default function Frame() {
  return (
    <ArtworkEditorScreen
      {...common}
      modeControl="menu"
      base={{ mode: "one", design: designs.hike }}
      colours={colours}
      previewed="black"
    />
  );
}
