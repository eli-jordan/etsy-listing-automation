export const meta = {
  title: "Marigold — mask editing, multiple placements · v5",
  viewport: "laptop",
  description: "The selected floating Mask / Unmask dock on a two-placement scene.",
};
import { MarigoldScreen } from "./_MarigoldScreen";
export default function Frame() {
  return <MarigoldScreen state="multiple" initialTool="exclude" />;
}
