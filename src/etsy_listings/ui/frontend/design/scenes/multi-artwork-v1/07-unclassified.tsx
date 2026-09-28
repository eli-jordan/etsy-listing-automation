import { ArtworkEditorScreen } from "./_snapshot/_ArtworkEditorScreen";
import { colours, common, lightDark } from "./_fixtures.ts";

export const meta = {
  title: "Artwork — colour not classified · v1",
  viewport: "laptop",
  description: "Heather isn't marked light or dark in the garment profile: deploy is blocked and the fix is named in the profile, not the listing.",
};

export default function Frame() {
  const withHeather = [...colours, { name: "heather", swatch: "#9b9a98", tone: null, enabled: true, own: null }].sort(
    (a, b) => a.name.localeCompare(b.name),
  );
  return <ArtworkEditorScreen {...common} base={lightDark} colours={withHeather} previewed="heather" />;
}
