export const meta = {
  title: "Marigold — multiple placements",
  viewport: "laptop",
  description:
    "The existing multiple-placement workbench with per-placement masks and shared preparation.",
};
import { MarigoldScreen } from "./_MarigoldScreen";
export default function Multiple() {
  return <MarigoldScreen state="multiple" />;
}
