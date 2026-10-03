import { ArtworkEditorScreen } from "./_snapshot/_ArtworkEditorScreen";
import { colours, common, designs } from "./_fixtures.ts";

export const meta = {
  title: "Artwork — one design · v2",
  viewport: "laptop",
  description: "One design for every shirt: today's workflow, with the light/dark choice beside it and each row showing what it prints.",
};

export default function Frame() {
  return <ArtworkEditorScreen {...common} base={{ mode: "one", design: designs.hike }} colours={colours} previewed="black" />;
}
