import { ArtworkEditorScreen } from "../../../screens/multiArtwork/ArtworkEditorScreen";
import { colours, common, lightDark } from "../_fixtures.ts";
import { StripB } from "../_StripB";

export const meta = {
  title: "B · mode tabs + design rail — light & dark",
  viewport: "laptop",
  description: "No dropdowns: a One design / Light & dark segmented control, big tiles for the chosen designs, and an always-visible recent-designs rail.",
};

export default function Frame() {
  return (
    <ArtworkEditorScreen
      {...common}
      base={lightDark}
      colours={colours}
      previewed="black"
      strip={(api) => <StripB api={api} />}
    />
  );
}
