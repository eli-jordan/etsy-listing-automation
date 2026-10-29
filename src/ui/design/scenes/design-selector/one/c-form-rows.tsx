import { ArtworkEditorScreen } from "../../../screens/multiArtwork/ArtworkEditorScreen";
import { colours, common, designs } from "../_fixtures.ts";
import { StripC } from "../_StripC";

export const meta = {
  title: "C · compact form rows — one design",
  viewport: "laptop",
  description: "The quietest option: a settings-style row with a checkbox to add a dark-shirts row. Dropping turns a row into a labelled drop zone.",
};

export default function Frame() {
  return (
    <ArtworkEditorScreen
      {...common}
      base={{ mode: "one", design: designs.hike }}
      colours={colours}
      previewed="black"
      strip={(api) => <StripC api={api} />}
    />
  );
}
