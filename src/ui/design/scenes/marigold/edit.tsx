export const meta = {
  title: "Marigold — placement & masks",
  viewport: "laptop",
  description: "The current template workbench with Marigold controls and fast placement preview.",
};
import { MarigoldScreen } from "./_MarigoldScreen";
export default function Edit() {
  return <MarigoldScreen state="edit" />;
}
