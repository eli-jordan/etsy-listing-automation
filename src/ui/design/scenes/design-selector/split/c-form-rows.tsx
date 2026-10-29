import { ArtworkEditorScreen } from "../../../screens/multiArtwork/ArtworkEditorScreen";
import { colours, common, lightDark } from "../_fixtures.ts";
import { StripC } from "../_StripC";

export const meta = {
  title: "C · compact form rows — light & dark",
  viewport: "laptop",
  description: "The quietest option: a settings-style row with a checkbox to add a dark-shirts row. Dropping turns a row into a labelled drop zone.",
};

export default function Frame() {
  return (
    <ArtworkEditorScreen
      {...common}
      base={lightDark}
      colours={colours}
      previewed="black"
      strip={(api) => <StripC api={api} />}
    />
  );
}
